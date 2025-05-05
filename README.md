# Tengo Bot

Voici le code source de Tengo Bot, un assistant Telegram que j'ai développé pour faciliter la recherche d'animes dans mon catalogue personnel.

## À propos de Tengo Bot

Tengo Bot est conçu pour aider les utilisateurs à trouver rapidement des informations sur les animes référencés dans une base de données spécifique (mon catalogue). Il peut répondre à des requêtes textuelles, analyser des images pour identifier des animes, et même transcrire des messages vocaux pour rechercher des informations. Il utilise l'API Gemini de Google pour comprendre les requêtes et générer des réponses pertinentes basées sur le contenu du catalogue.

Le bot est une interface directe à mon catalogue d'animes, rendant la navigation et la recherche d'informations beaucoup plus interactives qu'un simple fichier ou une liste statique.

## Fonctionnalités

*   **Recherche par Nom :** Trouvez des animes en utilisant leur titre principal, des titres alternatifs, des abréviations, ou même avec des fautes de frappe.
*   **Identification par Image :** Envoyez une image contenant un personnage ou une scène d'anime, et le bot essaiera d'identifier l'œuvre associée.
*   **Recherche Vocale :** Posez vos questions oralement ; le bot transcrira et traitera votre requête.
*   **Recommandations :** Demandez des suggestions d'animes par genre ou similaires à ceux que vous connaissez (parmi ceux présents dans le catalogue).
*   **Base de Connaissances Externe :** Le catalogue d'animes est lu depuis un fichier Markdown externe (local ou hébergé en ligne).

## Technologies Utilisées

*   **Python**
*   **`python-telegram-bot` :** Pour l'interaction avec l'API Telegram.
*   **`google-generativeai` :** Pour l'intégration de l'API Gemini (compréhension du langage, identification d'images, transcription).
*   **`python-dotenv` :** Pour gérer les variables d'environnement (tokens, clés API).
*   **`httpx` :** Utilisé pour le téléchargement du catalogue Markdown depuis une URL (si configuré).

## Configuration et Déploiement

Pour faire fonctionner Tengo Bot, vous aurez besoin de :

1.  Un token de bot Telegram (obtenu via BotFather).
2.  Une clé API Google Gemini.
3.  Un catalogue d'animes formaté en Markdown.

**Étapes :**

1.  **Clonez ce repository :**
    ```bash
    git clone https://github.com/Joyboy-dy/tengo_bot.git
    cd tengo_bot
    ```
2.  **Installez les dépendances Python :**
    ```bash
    pip install -r requirements.txt
    ```
3.  **Créez un fichier `.env` :** À la racine du projet, créez un fichier nommé `.env` et ajoutez-y les lignes suivantes, en remplaçant les valeurs par les vôtres :
    ```dotenv
    TELEGRAM_BOT_TOKEN="votre_token_telegram"
    GEMINI_API_KEY="votre_cle_api_gemini"
    MARKDOWN_EXPORT_PATH="chemin/vers/votre/catalogue.md"
    ```
    Assurez-vous que `MARKDOWN_EXPORT_PATH` pointe correctement vers votre fichier catalogue Markdown.
4.  **Préparez votre catalogue Markdown :** Votre catalogue doit être un fichier `.md` contenant les informations sur les animes que le bot pourra consulter. Le formatage interne du fichier (utilisation de gras, listes, liens) est important car le bot utilise Gemini pour l'analyser et extraire les informations pertinentes. Le code est optimisé pour reconnaître des structures simples avec des titres en gras, des alias entre parenthèses `(Alias: ...)`, et des listes.
5.  **Exécutez le bot :**
    ```bash
    python tengo.py 
    ```
    Pour une exécution en continu (déploiement), utilisez un gestionnaire de processus (`screen`, `tmux`, `systemd`) ou une plateforme d'hébergement adaptée aux applications qui font du polling.

## Contribuer

Ce projet est un projet personnel, mais si vous avez des suggestions ou des améliorations, n'hésitez pas à ouvrir une issue ou une Pull Request.

## Licence

Ce projet est distribué sous la licence Apache 2.0. Consultez le fichier `LICENSE` pour plus de détails.

---