# Copyright 2025 TENGO BY FELICIO DE SOUZA
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ___________________________________________________________________________
# -*- coding: utf-8 -*-
import os
import logging
import asyncio
from dotenv import load_dotenv
import datetime
import re
import html
from collections import deque
import io
import httpx

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler
)
from telegram.constants import ParseMode
from telegram.error import BadRequest

import google.generativeai as genai

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MARKDOWN_EXPORT_PATH = os.getenv("MARKDOWN_EXPORT_PATH", "messages.md")

MAX_CONTEXT_LENGTH = 900000
HISTORY_LENGTH = 12
MAX_VOICE_SIZE = 25 * 1024 * 1024
MAX_IMAGE_SIZE = 20 * 1024 * 1024

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

try:
    safety_settings = {}
    gemini_model = genai.GenerativeModel(
        'gemini-1.5-flash',
        safety_settings=safety_settings
    )
    genai.configure(api_key=GEMINI_API_KEY)
    logger.info(f"Gemini API configurée avec succès (modèle: {gemini_model.model_name}).")
except Exception as e:
    logger.critical(f"Erreur critique config Gemini: {e}", exc_info=True)
    gemini_model = None

BOT_NAME = "Tengo Bot"
CREATOR_NAME = "Félicio de SOUZA"
CREATOR_PSEUDO = "JOYBOY"
CREATOR_LINK = "https://www.feliciodev.xyz/"
MAIN_CHANNEL_NAME = "Anime Listing"
MAIN_CHANNEL_LINK = "https://t.me/animelisting_oc"
COLLECTION_LINK = "https://t.me/addlist/xCEpCGbzm1gyNzJk"

def read_markdown_export(source_path: str) -> tuple[str | None, str | None]:
    if source_path.startswith(('http://', 'https://')):
        logger.info(f"Tentative de téléchargement MD depuis URL: {source_path}")
        try:
            response = httpx.get(source_path, timeout=30)
            response.raise_for_status()
            content = response.text

            file_size = len(content)
            logger.info(f"Téléchargement OK. Taille: {file_size} chars.")
            if file_size == 0: return None, "Erreur interne: Source distante vide."
            return content, None
        except httpx.HTTPStatusError as e:
            logger.error(f"Erreur HTTP téléchargement MD ({source_path}): {e}", exc_info=True)
            return None, f"Erreur HTTP lors de l'accès à la source distante: {e.response.status_code}"
        except httpx.RequestError as e:
            logger.error(f"Erreur requête téléchargement MD ({source_path}): {e}", exc_info=True)
            return None, f"Erreur de requête lors de l'accès à la source distante: {e}"
        except Exception as e:
            logger.error(f"Erreur inattendue téléchargement MD ({source_path}): {e}", exc_info=True)
            return None, "Erreur interne lors du téléchargement des données distantes."
    else:
        try:
            absolute_path = os.path.abspath(source_path)
            logger.info(f"Tentative de lecture MD locale: {absolute_path}")
            with open(absolute_path, 'r', encoding='utf-8') as f: content = f.read()
            file_size = len(content)
            logger.info(f"Lecture locale OK. Taille: {file_size} chars.")
            if file_size == 0: return None, "Erreur interne: Source locale vide."
            return content, None
        except FileNotFoundError:
            logger.error(f"Fichier MD local non trouvé: {absolute_path}")
            return None, f"Erreur: Base de connaissances inaccessible (fichier non trouvé à {source_path}). Vérifiez le chemin."
        except Exception as e:
            logger.error(f"Erreur lecture MD locale ({absolute_path}): {e}", exc_info=True)
            return None, "Erreur interne lecture données locales."

def markdown_to_telegram_html(md_text: str) -> str:
    if not md_text: return ""
    text = html.escape(md_text)
    def code_block_replacer(match):
        inner_content = html.unescape(match.group(1).strip())
        safe_inner_content = html.escape(inner_content)
        return f'<pre>{safe_inner_content}</pre>'
    text = re.sub(r'```(?:[^\n]*\n)?(.*?)```', code_block_replacer, text, flags=re.DOTALL | re.MULTILINE)
    text = re.sub(r'`(.*?)`', r'<code>\1</code>', text)
    def link_replacer(match):
        link_text_escaped = match.group(1)
        url_escaped = match.group(2)
        url_decoded = html.unescape(url_escaped)
        if not url_decoded or not url_decoded.strip().startswith(('http', 'tg')):
            logger.warning(f"URL invalide ignorée: '{url_decoded}' pour '{html.unescape(link_text_escaped)}'")
            return link_text_escaped
        safe_url = html.escape(url_decoded, quote=True)
        return f'<a href="{safe_url}">{link_text_escaped}</a>'
    text = re.sub(r'\[([^\]]+)\]\(\s*([^\s\)]+)\s*\)', link_replacer, text)
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'(?<!\w)_(.*?)_(?!\w)', r'<i>\1</i>', text)
    text = re.sub(r'^(\s*[*+-]\s+)', '• ', text, flags=re.MULTILINE)
    text = re.sub(r'^(\s*\d+\.\s+)', '• ', text, flags=re.MULTILINE)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    return text.strip()

async def transcribe_voice(voice_data: bytes) -> str | None:
    if not gemini_model:
        logger.error("Tentative de transcription mais modèle Gemini non initialisé.")
        return None
    if not voice_data:
        logger.warning("Tentative de transcription de données vocales vides.")
        return None
    try:
        logger.info(f"Préparation de {len(voice_data)} octets audio pour transcription directe par Gemini...")
        mime_type = 'audio/ogg'
        audio_part = {"mime_type": mime_type, "data": voice_data}
        prompt = "Transcris cet audio en texte."
        logger.info("Envoi de la requête de transcription directe à Gemini...")
        response = await gemini_model.generate_content_async(
            [prompt, audio_part],
            request_options={"timeout": 120}
        )
        logger.info("Réponse de transcription reçue de Gemini.")
        if response and response.candidates:
            first_candidate = response.candidates[0]
            if first_candidate.content and first_candidate.content.parts:
                transcribed_text = first_candidate.content.parts[0].text.strip()
                logger.info(f"Transcription réussie: '{transcribed_text}'")
                return transcribed_text if transcribed_text else None
            elif first_candidate.finish_reason and first_candidate.finish_reason != 1:
                 reason = first_candidate.finish_reason
                 map_r = {3:"Sécurité", 2:"Longueur Max", 4:"Récitation", 5: "Autre"}
                 txt = map_r.get(reason,"Inconnue")
                 logger.warning(f"Transcription Gemini arrêtée prématurément. Raison: {txt} ({reason})")
                 return None
            else:
                 logger.warning(f"Réponse de transcription Gemini inattendue (pas de contenu/partie texte): {response}")
                 return None
        elif response and hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
             block_reason = response.prompt_feedback.block_reason
             logger.warning(f"Requête de transcription bloquée par Gemini. Raison: {block_reason}")
             return None
        else:
            logger.warning(f"Réponse de transcription Gemini vide ou mal formée: {response}")
            return None
    except Exception as e:
        logger.error(f"Erreur lors de la transcription audio avec Gemini: {e}", exc_info=True)
        return None

async def identify_image_anime(image_data: bytes) -> str | None:
    if not gemini_model: return None
    try:
        logger.info(f"Envoi {len(image_data)} octets image à Gemini...")
        image_part = {"mime_type": "image/jpeg", "data": image_data}
        prompt = """Analyse cette image. Si elle contient un personnage ou une scène reconnaissable d'un anime ou manga, réponds UNIQUEMENT avec le nom le plus probable et le plus connu de cet anime/manga (privilégie le titre anglais ou romaji si possible, mais le plus courant). Ne donne aucune autre information. Si tu ne reconnais pas d'anime/manga spécifique ou si ce n'est pas pertinent, réponds "Inconnu"."""
        response = await gemini_model.generate_content_async(
            [prompt, image_part],
            request_options={"timeout": 60}
        )
        logger.info("Réponse identification image reçue.")
        if response and response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
             identified_name = response.text.strip()
             if identified_name and identified_name.lower() != "inconnu" and len(identified_name) < 100:
                 logger.info(f"Anime/Manga identifié: '{identified_name}'")
                 return identified_name
             else:
                 logger.info(f"Identification image non concluante ou 'Inconnu'. Réponse: '{identified_name}'")
                 return None
        else:
            logger.warning(f"Réponse identification image invalide ou bloquée: {response}")
            return None
    except Exception as e:
        logger.error(f"Erreur identification image Gemini: {e}", exc_info=True)
        return None

async def ask_gemini(query: str, static_context: str, chat_history: list) -> str:
    if not gemini_model: return "Désolé, le service IA est temporairement indisponible."
    if not static_context: return "Désolé, je ne peux pas accéder à ma base de connaissances actuellement."

    system_prompt = f"""Tu es {BOT_NAME}, un assistant IA expert en animes, créé par {CREATOR_NAME} ({CREATOR_LINK}) pour le catalogue Telegram de {CREATOR_PSEUDO} ({MAIN_CHANNEL_NAME} : {MAIN_CHANNEL_LINK}, Collection: {COLLECTION_LINK}).

**MISSION PRINCIPALE :** Aider les utilisateurs à trouver des informations précises sur les animes **présents dans le CONTEXTE (le catalogue fourni)**.

**RÈGLES CRUCIALES DE FONCTIONNEMENT :**

1.  **ÉTAPE 1 : INTERPRÉTATION INTELLIGENTE DE LA REQUÊTE**
    *   Analyse la 'QUESTION ACTUELLE' et l''HISTORIQUE'. **Utilise ta vaste connaissance générale des animes pour identifier l'anime REELLEMENT visé par l'utilisateur.**
    *   **TRÈS IMPORTANT : TITRES ALTERNATIFS.** Un anime peut être appelé par son nom anglais, japonais (romaji), français, des abréviations, ou même avec des fautes de frappe. Tu DOIS reconnaître ces variations. Exemples :
        *   "Tate no Yuusha no Nariagari" ou "shield hero" ou "tate no yusha" => **The Rising of the Shield Hero**
        *   "SNK", "Shingeki", "Attack on Titan" => **Shingeki No Kyojin**
        *   "jujutsu", "jujutsu kaisen", "jjk" => **Jujutsu Kaisen**
        *   "hill's parader" => **Hell's Paradise**
    *   **Ne mentionne JAMAIS explicitement que tu as corrigé ou interprété un titre.** Fais-le naturellement.
    *   **Prends en compte les indices de l'HISTORIQUE.** Si l'utilisateur clarifie un nom ("Tate no Yuusha c'est The Rising of the Shield Hero"), utilise cette information !

2.  **ÉTAPE 2 : RECHERCHE EXHAUSTIVE DANS LE CONTEXTE**
    *   Une fois l'anime probable identifié (avec ses variations de nom possibles), **cherche TOUTES ces variations activement dans le 'CONTEXTE (Export du catalogue)'**. Ton but est de trouver l'entrée correspondante, PEU IMPORTE comment elle est écrite dans le catalogue. Le contexte fourni contient déjà des alias sous la forme `(Alias: ...)`. Utilise-les prioritairement dans ta recherche.
    *   La recherche doit être flexible (majuscules/minuscules, accents, ponctuation partielle).

3.  **ÉTAPE 3 : GÉNÉRATION DE LA RÉPONSE BASÉE STRICTEMENT SUR LE CONTEXTE**
    *   **SI TROUVÉ DANS LE CONTEXTE :**
        *   Base ta réponse **EXCLUSIVEMENT** sur les informations trouvées pour cet anime DANS LE CONTEXTE.
        *   Utilise le **TITRE PRINCIPAL EXACT** (celui en gras `**...**`) et le formatage présents dans le CONTEXTE pour présenter l'information (saisons, statuts, liens). N'affiche pas les `(Alias: ...)` dans la réponse finale.
        *   Respecte le format Markdown demandé (Règle 5).
    *   **SI NON TROUVÉ DANS LE CONTEXTE (après recherche exhaustive) :**
        *   Réponds clairement que tu n'as pas trouvé d'information sur cet anime **dans le catalogue consulté**. Utilise le nom principal que tu as identifié (celui le plus probable ou celui utilisé par l'utilisateur si non ambigu). Exemple : "D'après le catalogue que j'ai consulté, je n'ai pas trouvé d'information sur '**The Rising of the Shield Hero**'."
        *   **Ne propose PAS d'alternatives** sauf si l'utilisateur demande explicitement des recommandations (voir Règle 4).

4.  **RECOMMANDATIONS (Si demandé explicitement)**
    *   Si on te demande des animes *similaires* à X, ou des animes d'un *genre* Y :
        a. Identifie le(s) genre(s) pertinent(s) (utilise ta connaissance générale).
        b. Cherche DANS LE CONTEXTE les animes correspondant à ce(s) genre(s).
        c. Liste ceux que tu trouves, en précisant si l'anime X de référence n'était pas lui-même dans le catalogue.
        d. Si rien n'est trouvé pour ce genre DANS LE CONTEXTE, dis-le clairement.

5.  **FORMATAGE (Markdown à générer - Strictement Appliqué):**
    *   Liens: `[Texte du lien](URL_VALIDE_DU_CONTEXTE)` (pas de lien si URL absente).
    *   Titres d'animes: `**Texte**` (tel qu'écrit dans le contexte, sans les alias).
    *   Statuts: `_Texte_` (_VF_, _Saison 2_, etc.).
    *   Listes: `* ` (un item principal par puce).
    *   Clarté, concision, pas de blabla inutile. Paragraphes si nécessaire.

6.  **CONFIDENTIALITÉ ABSOLUE DE LA SOURCE :** Ne mentionne JAMAIS le fichier, l'export, la date, le contexte statique, ou tes mécanismes internes de recherche/correction. Agis comme une interface directe au catalogue.
"""
    formatted_history = "\n".join(
        [f"Utilisateur: {msg['parts'][0]}" if msg['role'] == 'user' else f"{BOT_NAME}: {msg['parts'][0]}"
         for msg in chat_history if msg.get('parts')]
    )

    logger.info(f"Préparation du prompt OPTIMISÉ pour Gemini. Requête: '{query}'. Taille contexte: {len(static_context)} chars. Hist: {len(chat_history)} msgs.")

    full_prompt = f"""{system_prompt}

HISTORIQUE DE LA CONVERSATION :
--- DEBUT HISTORIQUE ---
{formatted_history if formatted_history else "Aucun historique pour cette conversation."}
--- FIN HISTORIQUE ---

CONTEXTE (Export du catalogue d'animes - Ta SEULE source pour la disponibilité, les détails et les liens. Contient des `(Alias: ...)` pour t'aider) :
--- DEBUT DU CONTENU EXPORTÉ ---
{static_context}
--- FIN DU CONTENU EXPORTÉ ---

QUESTION ACTUELLE DE L'UTILISATEUR :
"{query}"

TA RÉPONSE ({BOT_NAME} - Applique rigoureusement les étapes 1, 2, 3 et les règles. Format Markdown. N'affiche PAS les alias dans la réponse finale) :
"""

    try:
        logger.info(f"Envoi requête OPTIMISÉE à Gemini...")
        response = await gemini_model.generate_content_async(
            full_prompt,
            request_options={"timeout": 180}
            )
        logger.info("Réponse reçue de Gemini (optimisé).")

        if response and response.candidates:
            first_candidate = response.candidates[0]
            if first_candidate.content and first_candidate.content.parts:
                return first_candidate.content.parts[0].text
            elif first_candidate.finish_reason and first_candidate.finish_reason != 1:
                 reason = first_candidate.finish_reason
                 map_r = {3:"Sécurité", 2:"Longueur Max", 4:"Récitation", 5:"Autre"}
                 txt = map_r.get(reason,"Inconnue")
                 logger.warning(f"Réponse Gemini incomplète ou arrêtée (optimisé). Raison: {txt} ({reason})")
                 safety_ratings = getattr(first_candidate, 'safety_ratings', None)
                 if safety_ratings: logger.warning(f"Safety Ratings: {safety_ratings}")
                 return f"Désolé, ma réponse a été interrompue ({txt}). Pouvez-vous reformuler ?"
            else:
                 logger.warning(f"Réponse Gemini inattendue (pas de contenu/partie texte) (optimisé): {response}")
                 return "Désolé, j'ai reçu une réponse inattendue de l'IA."
        elif response and hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
             block_reason = response.prompt_feedback.block_reason
             logger.warning(f"Requête bloquée par Gemini (optimisé). Raison: {block_reason}")
             safety_feedback = getattr(response.prompt_feedback, 'safety_ratings', 'N/A')
             logger.warning(f"Safety Feedback (Prompt): {safety_feedback}")
             return f"Désolé, votre requête n'a pas pu être traitée pour des raisons de sécurité ou de politique (Raison: {block_reason})."
        else:
            logger.warning(f"Réponse Gemini vide ou mal formée (optimisé): {response}")
            return "Désolé, il y a eu un problème de communication avec l'IA."

    except Exception as e:
        logger.error(f"Erreur lors de l'appel à Gemini (optimisé): {e}", exc_info=True)
        if "deadline exceeded" in str(e).lower() or "timeout" in str(e).lower():
             return "Désolé, la requête a pris trop de temps. Veuillez réessayer ou simplifier votre demande."
        return "Désolé, une erreur technique est survenue lors de la communication avec l'IA."

async def process_query_and_respond(
    user_query: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    processing_message = None
):
    chat_id = update.effective_chat.id
    message_id = update.effective_message.id
    user_info = update.effective_user
    username = user_info.username or user_info.first_name

    if not user_query or user_query.isspace():
        logger.warning(f"Requête vide reçue de {username} (Chat ID: {chat_id}).")
        error_text = "Hmm, votre message semble vide. Que puis-je faire pour vous ?"
        try:
            if processing_message:
                await context.bot.edit_message_text(chat_id=chat_id, message_id=processing_message.message_id, text=error_text)
            else:
                await update.effective_message.reply_text(error_text, reply_to_message_id=message_id)
        except Exception as e:
            logger.error(f"Impossible d'envoyer le message 'requête vide' à {username}: {e}")
        return

    logger.info(f"Traitement de la requête de {username} (Chat ID: {chat_id}): '{user_query[:100]}...'")

    chat_history = context.chat_data.setdefault('history', deque(maxlen=HISTORY_LENGTH))
    if not chat_history or chat_history[-1].get("role") != "user" or chat_history[-1].get("parts", [""])[0] != user_query:
         chat_history.append({"role": "user", "parts": [user_query]})
         logger.debug(f"Requête ajoutée à l'historique (Chat {chat_id}). Nouvelle taille: {len(chat_history)}")
    else:
         logger.debug(f"Requête identique à la précédente, non ajoutée à l'historique (Chat {chat_id}).")
    history_list = list(chat_history)

    static_channel_context, file_read_error_msg = read_markdown_export(MARKDOWN_EXPORT_PATH)
    if not static_channel_context:
         error_text = file_read_error_msg or "Erreur critique : impossible d'accéder aux données nécessaires."
         logger.error(f"Échec lecture contexte pour {username}: {error_text}")
         if chat_history and chat_history[-1].get("role") == "user":
             chat_history.pop()
         try:
             if processing_message:
                 await context.bot.edit_message_text(chat_id=chat_id, message_id=processing_message.message_id, text=error_text)
             else:
                 await update.effective_message.reply_text(error_text, reply_to_message_id=message_id)
         except Exception as e:
             logger.error(f"Impossible d'envoyer l'erreur de lecture de fichier à {username}: {e}")
         return

    gemini_response_md = await ask_gemini(user_query, static_channel_context, history_list)

    is_error_response = gemini_response_md.lower().startswith(("désolé", "erreur", "hmm", "je ne peux pas", "impossible"))
    if not is_error_response and gemini_response_md and not gemini_response_md.isspace():
        chat_history.append({"role": "model", "parts": [gemini_response_md]})
        context.chat_data['history'] = chat_history
        logger.info(f"Réponse modèle ajoutée à l'historique (Chat {chat_id}). Taille: {len(chat_history)}")
    else:
        logger.info(f"Réponse modèle (erreur ou vide) non ajoutée à l'historique (Chat {chat_id}). Réponse: '{gemini_response_md[:100]}...'")

    gemini_response_html = markdown_to_telegram_html(gemini_response_md)

    try:
        if processing_message:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=processing_message.message_id,
                text=gemini_response_html or "...", parse_mode=ParseMode.HTML,
                disable_web_page_preview=True )
            logger.info(f"Réponse éditée envoyée à {username} (Chat ID: {chat_id})")
        else:
            await update.effective_message.reply_html(
                text=gemini_response_html or "...", reply_to_message_id=message_id,
                disable_web_page_preview=True )
            logger.info(f"Nouvelle réponse envoyée à {username} (Chat ID: {chat_id})")
    except BadRequest as e:
        logger.error(f"Erreur BadRequest lors de l'envoi HTML à {username}: {e}. Tentative avec Markdown brut.")
        fallback_text = gemini_response_md + "\n\n_(Erreur d'affichage : formatage complexe non supporté)_"
        await send_fallback_response(context, chat_id, processing_message, message_id, fallback_text, "", username)
    except Exception as e:
        logger.error(f"Erreur inattendue lors de l'envoi de la réponse à {username}: {e}", exc_info=True)
        fallback_text = gemini_response_md + "\n\n_(Erreur technique lors de l'affichage de la réponse)_"
        await send_fallback_response(context, chat_id, processing_message, message_id, fallback_text, "", username)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id
    username = user.username or user.first_name
    logger.info(f"Commande /start reçue de {username} (Chat ID: {chat_id})")
    if 'history' in context.chat_data:
        context.chat_data['history'].clear()
        logger.info(f"Historique de conversation effacé pour {username} (Chat ID: {chat_id})")
    text = (f"👋 Bonjour {user.mention_html()} !\n\n"
            f"Je suis <b>{BOT_NAME}</b>, votre assistant expert pour rechercher des animes dans le catalogue de <b>{MAIN_CHANNEL_NAME}</b> ({CREATOR_PSEUDO}).\n\n"
            "Comment puis-je vous aider ?\n"
            "• Donnez-me un nom d'anime (anglais, romaji...)\n"
            "• Envoyez une image 🖼️ ou un vocal 🗣️\n"
            "• Demandez une recommandation par genre")
    keyboard = [[InlineKeyboardButton(f"👤 Créateur ({CREATOR_PSEUDO})", url=CREATOR_LINK)],
                [InlineKeyboardButton(f"📜 Catalogue ({MAIN_CHANNEL_NAME})", url=MAIN_CHANNEL_LINK)],
                [InlineKeyboardButton("📂 Collection Complète", url=COLLECTION_LINK)],
                [InlineKeyboardButton("❓ Aide (/help)", callback_data="help_callback")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try: await update.message.reply_html(text, reply_markup=reply_markup)
    except Exception as e: logger.error(f"Erreur envoi message /start à {username}: {e}")

async def help_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    username = user.username or user.first_name
    logger.info(f"Commande /help reçue de {username}")
    await send_help_message(update.message.chat_id, context)

async def help_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = query.from_user
    username = user.username or user.first_name
    await query.answer()
    logger.info(f"Callback 'help_callback' reçu de {username}")
    await send_help_message(query.message.chat_id, context)

async def send_help_message(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    text = f"""
❓ <b>Comment utiliser {BOT_NAME} ?</b>

Je suis votre expert pour explorer le catalogue d'animes de <a href="{MAIN_CHANNEL_LINK}">{MAIN_CHANNEL_NAME}</a>.

➡️ <b>Mes capacités :</b>
   • 📝 <b>Recherche par Nom :</b> Donnez-moi n'importe quel nom d'anime (Anglais, Romaji, Japonais, abréviation...). Je ferai de mon mieux pour le reconnaître et chercher dans le catalogue (ex: <i>"Shield Hero"</i>, <i>"Tate no Yuusha"</i>, <i>"SNK"</i>).
   • 🖼️ <b>Recherche par Image :</b> Envoyez une image, j'identifierai l'anime et vérifierai sa présence dans le catalogue.
   • 🗣️ <b>Recherche Vocale :</b> Posez votre question à voix haute.
   • 💡 <b>Recommandations :</b> Demandez des suggestions par genre (<i>"des isekai présents dans le catalogue"</i>) ou similaires à un autre anime.
   • 💬 <b>Conversation :</b> N'hésitez pas à préciser votre demande ou à poser des questions de suivi.

🧠 <b>Ma méthode :</b>
   1. Je comprends votre demande en utilisant ma connaissance des animes.
   2. Je cherche l'anime correspondant (et ses titres alternatifs) DANS le catalogue fourni par {CREATOR_PSEUDO}.
   3. Je vous donne les informations EXACTES trouvées dans ce catalogue (liens, saisons, etc.). Si rien n'est trouvé, je vous le dis clairement.

✨ <b>Conseil :</b> Même si je reconnais les variations, un nom précis aide toujours !

🔗 <b>Liens Utiles :</b>
"""
    keyboard = [[InlineKeyboardButton(f"👤 Créateur ({CREATOR_PSEUDO})", url=CREATOR_LINK)],
                [InlineKeyboardButton(f"📜 Catalogue ({MAIN_CHANNEL_NAME})", url=MAIN_CHANNEL_LINK)],
                [InlineKeyboardButton("📂 Collection Complète", url=COLLECTION_LINK)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except BadRequest as e:
         logger.error(f"Erreur BadRequest envoi aide HTML: {e}. Fallback texte.")
         fallback_text = f"Aide {BOT_NAME}: Recherche animes (noms variés, image, vocal) dans catalogue {MAIN_CHANNEL_NAME}. Recommandations possibles. Liens: Créateur {CREATOR_LINK}, Catalogue {MAIN_CHANNEL_LINK}, Collection {COLLECTION_LINK}."
         await context.bot.send_message(chat_id=chat_id, text=fallback_text)
    except Exception as e:
         logger.error(f"Erreur générale envoi aide: {e}")
         await context.bot.send_message(chat_id=chat_id, text="Impossible d'afficher l'aide pour le moment.")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message; voice = message.voice
    user_info = update.effective_user; username = user_info.username or user_info.first_name
    chat_id = update.effective_chat.id
    logger.info(f"Message vocal reçu de {username} (Chat ID: {chat_id}, Durée: {voice.duration}s, Taille: {voice.file_size} octets)")
    if voice.file_size > MAX_VOICE_SIZE:
        logger.warning(f"Message vocal de {username} trop volumineux ({voice.file_size} > {MAX_VOICE_SIZE})")
        await message.reply_text(f"Désolé, ce message vocal est trop volumineux (max {MAX_VOICE_SIZE // (1024*1024)} Mo).")
        return
    processing_message = None
    try: processing_message = await message.reply_text("🗣️ Traitement de votre message vocal...")
    except Exception as e: logger.error(f"Impossible d'envoyer le message 'Traitement vocal...' à {username}: {e}")
    try:
        voice_file = await voice.get_file()
        voice_data = bytes(await voice_file.download_as_bytearray())
        logger.info(f"Téléchargement audio OK ({len(voice_data)} octets) pour {username}.")
        transcribed_text = await transcribe_voice(voice_data)
        if transcribed_text:
            logger.info(f"Texte transcrit pour {username}: '{transcribed_text[:100]}...'")
            await process_query_and_respond(transcribed_text, update, context, processing_message)
        else:
            logger.warning(f"Échec de la transcription pour {username} (Chat ID: {chat_id}).")
            error_text = "Désolé, je n'ai pas pu comprendre ou traiter ce message vocal. Veuillez réessayer ou envoyer un message texte."
            if processing_message: await context.bot.edit_message_text(chat_id=chat_id, message_id=processing_message.message_id, text=error_text)
            else: await message.reply_text(error_text, reply_to_message_id=message.message_id)
    except Exception as e:
        logger.error(f"Erreur générale lors du traitement du message vocal de {username}: {e}", exc_info=True)
        error_text = "Une erreur inattendue est survenue lors du traitement de votre message vocal."
        try:
            if processing_message: await context.bot.edit_message_text(chat_id=chat_id, message_id=processing_message.message_id, text=error_text)
            else: await message.reply_text(error_text, reply_to_message_id=message.message_id)
        except Exception as send_e: logger.error(f"Impossible d'envoyer l'erreur de traitement vocal à {username}: {send_e}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message.photo: return
    photo = message.photo[-1]
    user_info = update.effective_user; username = user_info.username or user_info.first_name
    chat_id = update.effective_chat.id
    logger.info(f"Photo reçue de {username} (Chat ID: {chat_id}, Taille: {photo.file_size} octets)")
    if photo.file_size > MAX_IMAGE_SIZE:
        logger.warning(f"Photo de {username} trop volumineuse ({photo.file_size} > {MAX_IMAGE_SIZE})")
        await message.reply_text(f"Désolé, cette image est trop volumineuse (max {MAX_IMAGE_SIZE // (1024*1024)} Mo).")
        return
    processing_message = None
    try: processing_message = await message.reply_text("🖼️ Analyse de l'image...")
    except Exception as e: logger.error(f"Impossible d'envoyer le message 'Analyse image...' à {username}: {e}")
    try:
        image_file = await photo.get_file()
        image_data = bytes(await image_file.download_as_bytearray())
        logger.info(f"Téléchargement image OK ({len(image_data)} octets) pour {username}.")
        identified_query = await identify_image_anime(image_data)
        if identified_query:
            logger.info(f"Anime identifié depuis l'image de {username}: '{identified_query}'")
            query_for_processing = identified_query
            history_note_query = f"(Image envoyée par l'utilisateur, identifiée comme : {identified_query})"
            chat_history = context.chat_data.setdefault('history', deque(maxlen=HISTORY_LENGTH))
            chat_history.append({"role": "user", "parts": [history_note_query]})
            await process_query_and_respond(query_for_processing, update, context, processing_message)
        else:
            logger.info(f"Impossible d'identifier un anime dans l'image de {username}.")
            error_text = "Désolé, je n'ai pas réussi à reconnaître un anime spécifique dans cette image. Vous pouvez essayer avec le nom ?"
            if processing_message: await context.bot.edit_message_text(chat_id=chat_id, message_id=processing_message.message_id, text=error_text)
            else: await message.reply_text(error_text, reply_to_message_id=message.message_id)
    except Exception as e:
        logger.error(f"Erreur générale lors du traitement de la photo de {username}: {e}", exc_info=True)
        error_text = "Une erreur inattendue est survenue lors de l'analyse de l'image."
        try:
            if processing_message: await context.bot.edit_message_text(chat_id=chat_id, message_id=processing_message.message_id, text=error_text)
            else: await message.reply_text(error_text, reply_to_message_id=message.message_id)
        except Exception as send_e: logger.error(f"Impossible d'envoyer l'erreur de traitement photo à {username}: {send_e}")

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.edited_message:
        logger.info(f"Message édité ignoré de {update.effective_user.username or update.effective_user.first_name}")
        return
    user_query = update.message.text
    await process_query_and_respond(user_query, update, context, processing_message=None)

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    command = update.message.text
    username = update.effective_user.username or update.effective_user.first_name
    logger.info(f"Commande inconnue '{command}' reçue de {username}")
    await update.message.reply_text("Désolé, je ne reconnais pas cette commande. Utilisez /help pour voir ce que je peux faire.")

async def send_fallback_response(context: ContextTypes.DEFAULT_TYPE, chat_id: int, processing_message, original_msg_id: int, fallback_text: str, error_indicator: str, username: str):
    logger.warning(f"Tentative d'envoi de réponse fallback à {username} (Chat ID: {chat_id}).")
    full_fallback_text = fallback_text
    try:
        if processing_message:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=processing_message.message_id, text=full_fallback_text,
                parse_mode=None, disable_web_page_preview=True )
        else:
            await context.bot.send_message(
                chat_id=chat_id, text=full_fallback_text, reply_to_message_id=original_msg_id,
                parse_mode=None, disable_web_page_preview=True )
        logger.info(f"Réponse fallback envoyée avec succès à {username}")
    except Exception as final_e:
        logger.error(f"ÉCHEC CRITIQUE : Impossible d'envoyer MÊME la réponse fallback à {username}: {final_e}", exc_info=True)
        try:
            if not processing_message:
                 await context.bot.send_message(chat_id=chat_id, text="Désolé, une erreur est survenue lors de l'affichage de ma réponse.", reply_to_message_id=original_msg_id)
        except Exception as ultra_final_e:
             logger.critical(f"Impossible d'envoyer le message d'erreur final à {username}: {ultra_final_e}")

def main() -> None:
    if not TELEGRAM_BOT_TOKEN: logger.critical("ERREUR CRITIQUE: TELEGRAM_BOT_TOKEN manquant."); return
    if not GEMINI_API_KEY: logger.critical("ERREUR CRITIQUE: GEMINI_API_KEY manquant."); return

    is_url = MARKDOWN_EXPORT_PATH.startswith(('http://', 'https://'))
    if not is_url and (not MARKDOWN_EXPORT_PATH or not os.path.exists(MARKDOWN_EXPORT_PATH)):
         logger.critical(f"ERREUR CRITIQUE: MARKDOWN_EXPORT_PATH ('{MARKDOWN_EXPORT_PATH}') non trouvé ou invalide (et n'est pas une URL).")
         if not is_url:
             try: logger.critical(f"Chemin absolu tenté : {os.path.abspath(MARKDOWN_EXPORT_PATH)}")
             except Exception: pass
         return

    if not gemini_model: logger.critical("ERREUR CRITIQUE: Modèle Gemini non initialisé."); return

    logger.info(f"Démarrage de {BOT_NAME}...")
    if is_url:
        logger.info(f"Utilisation du fichier Markdown depuis URL: {MARKDOWN_EXPORT_PATH}")
    else:
        logger.info(f"Utilisation du fichier Markdown local: {os.path.abspath(MARKDOWN_EXPORT_PATH)}")
    logger.info(f"Modèle Gemini utilisé: {gemini_model.model_name}")

    try:
        application = (Application.builder().token(TELEGRAM_BOT_TOKEN)
                       .connect_timeout(30).read_timeout(40).write_timeout(40).pool_timeout(30)
                       .concurrent_updates(10)
                       .build())

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command_handler))
        application.add_handler(MessageHandler(filters.VOICE & ~filters.COMMAND, handle_voice))
        application.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_photo))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.UpdateType.EDITED_MESSAGE, handle_text_message))
        application.add_handler(CallbackQueryHandler(help_callback_handler, pattern="^help_callback$"))
        application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

        logger.info(f"{BOT_NAME} est prêt et écoute les mises à jour Telegram...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

    except Exception as e:
        logger.critical(f"Erreur critique lors de l'initialisation ou de l'exécution du bot: {e}", exc_info=True)
    finally:
        logger.info(f"Arrêt de {BOT_NAME}... Script terminé.")

if __name__ == "__main__":
    main()