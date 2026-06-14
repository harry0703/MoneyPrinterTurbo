<div align="center">
<h1 align="center">MoneyPrinterTurbo 💸</h1>

<p align="center">
  <a href="https://github.com/harry0703/MoneyPrinterTurbo/stargazers"><img src="https://img.shields.io/github/stars/harry0703/MoneyPrinterTurbo.svg?style=for-the-badge" alt="Étoiles"></a>
  <a href="https://github.com/harry0703/MoneyPrinterTurbo/issues"><img src="https://img.shields.io/github/issues/harry0703/MoneyPrinterTurbo.svg?style=for-the-badge" alt="Issues"></a>
  <a href="https://github.com/harry0703/MoneyPrinterTurbo/network/members"><img src="https://img.shields.io/github/forks/harry0703/MoneyPrinterTurbo.svg?style=for-the-badge" alt="Forks"></a>
  <a href="https://github.com/harry0703/MoneyPrinterTurbo/blob/main/LICENSE"><img src="https://img.shields.io/github/license/harry0703/MoneyPrinterTurbo.svg?style=for-the-badge" alt="Licence"></a>
</p>

<h3><a href="README-en.md">English</a> | <a href="README.md">简体中文</a> | <a href="README-ar.md">العربية</a> | Français</h3>

<div align="center">
  <a href="https://trendshift.io/repositories/8731" target="_blank"><img src="https://trendshift.io/api/badge/repositories/8731" alt="harry0703%2FMoneyPrinterTurbo | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
</div>

Fournissez simplement un <b>sujet</b> ou un <b>mot-clé</b> pour une vidéo, et l'outil génère automatiquement le script, les visuels, les sous-titres et la musique de fond, puis assemble une courte vidéo en haute définition.

<p align="center">
  <sub>
    Merci à <a href="https://aihubmix.com/?aff=CEve">AIHubMix</a> pour son soutien à ce projet. AIHubMix donne accès à OpenAI, Claude, Gemini, DeepSeek, Qwen et 700+ modèles en un seul point d'entrée.
  </sub>
</p>

### Interface Web

![](docs/webui-en.jpg)

### Interface API

![](docs/api.jpg)

</div>

## Fonctionnalités 🎯

- [x] Architecture **MVC complète**, code **bien structuré**, facile à maintenir, supporte `API` et `interface web`
- [x] Génération du script par **IA** ou saisie d'un **script personnalisé**
- [x] Plusieurs formats vidéo **haute définition**
  - [x] Portrait 9:16, `1080x1920`
  - [x] Paysage 16:9, `1920x1080`
- [x] **Génération par lots** : créer plusieurs vidéos simultanément, puis choisir la meilleure
- [x] Durée des **clips vidéo** configurable
- [x] Scripts en **chinois** et **anglais** (et d'autres langues selon le modèle LLM)
- [x] **Synthèse vocale** avec plusieurs voix et **prévisualisation en temps réel**
- [x] **Sous-titres** avec réglage de la `police`, `position`, `couleur`, `taille` et `contour`
- [x] **Musique de fond** aléatoire ou personnalisée, avec réglage du volume
- [x] Sources vidéo **HD** et **libres de droits** + support des **fichiers locaux**
- [x] Sources vidéo : **Pexels**, **Pixabay**, **Coverr** (HD/4K gratuit, soumis aux [conditions de licence Coverr](https://coverr.co/license))
- [x] Compatible avec **OpenAI**, **AIHubMix**, **Moonshot**, **Azure**, **gpt4free**, **one-api**, **Qwen**, **Google Gemini**, **Ollama**, **DeepSeek**, **MiniMax**, **ERNIE**, **Pollinations**, **ModelScope**, et plus encore

## Configuration requise 📦

- Plateformes recommandées : Windows 10+, macOS 11+, ou une distribution Linux courante
- Un GPU n'est pas obligatoire, mais améliore la transcription locale, le traitement vidéo et la génération en lots

| Composant | Minimum   | Recommandé   | Optimal     |
|-----------|-----------|--------------|-------------|
| CPU       | 4 cœurs   | 6 à 8 cœurs  | 8+ cœurs    |
| RAM       | 4 Go      | 8 Go         | 16+ Go      |
| GPU       | Non requis| 4+ Go VRAM   | 8+ Go VRAM  |

- Si vous utilisez principalement des LLM cloud, TTS cloud et des sources vidéo en ligne, le CPU et la RAM priment sur le GPU
- Si vous utilisez `faster-whisper`, la génération en lots ou un traitement local intensif, un GPU améliore notablement les performances

---

## Tutoriel d'installation étape par étape 🚀

### Méthode 1 — Docker (recommandée, la plus simple)

> Convient à tous les systèmes (Windows, macOS, Linux). Aucune gestion de Python requise.

**Étape 1 — Installer Docker Desktop**

Téléchargez et installez Docker Desktop : https://www.docker.com/products/docker-desktop/

Sur Windows, Docker Desktop nécessite WSL 2 :
- Guide WSL : https://learn.microsoft.com/fr-fr/windows/wsl/install
- Guide Docker + WSL : https://learn.microsoft.com/fr-fr/windows/wsl/tutorials/wsl-containers

**Étape 2 — Cloner le dépôt**

```shell
git clone https://github.com/harry0703/MoneyPrinterTurbo.git
cd MoneyPrinterTurbo
```

**Étape 3 — Créer le fichier de configuration**

```shell
cp config.example.toml config.toml
```

Ouvrez `config.toml` et renseignez au minimum :
- `pexels_api_keys` — clé(s) API Pexels (inscription gratuite sur https://www.pexels.com/api/)
- `llm_provider` — par exemple `openai`, `aihubmix`, `deepseek`, `ollama`…
- La clé API correspondant au fournisseur LLM choisi

**Étape 4 — Lancer les conteneurs**

```shell
docker compose up
```

> Sur les versions récentes de Docker, la commande est `docker compose up` (sans tiret). Sur les anciennes versions : `docker-compose up`.

**Étape 5 — Accéder à l'application**

- Interface web : http://127.0.0.1:8501
- Documentation API : http://127.0.0.1:8080/docs

---

### Méthode 2 — Installation locale avec uv (macOS / Linux)

> Méthode recommandée sur macOS et Linux. `uv` gère automatiquement la version de Python.

**Étape 1 — Installer uv**

```shell
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Étape 2 — Cloner le dépôt**

```shell
git clone https://github.com/harry0703/MoneyPrinterTurbo.git
cd MoneyPrinterTurbo
```

**Étape 3 — Installer Python 3.11 et les dépendances**

```shell
uv python install 3.11
uv sync --frozen
```

**Étape 4 — Créer et configurer `config.toml`**

```shell
cp config.example.toml config.toml
```

Éditez `config.toml` :
- `pexels_api_keys` — clé(s) API Pexels
- `llm_provider` — fournisseur LLM
- Clé API du fournisseur LLM

**Étape 5 — Lancer l'interface web**

```shell
uv run streamlit run ./webui/Main.py --browser.gatherUsageStats=False
```

Ou via le script fourni :

```shell
sh webui.sh
```

Le navigateur s'ouvre automatiquement sur http://localhost:8501

**Étape 6 (optionnel) — Lancer le serveur API**

```shell
uv run python main.py
```

API disponible sur http://127.0.0.1:8080/docs

---

### Méthode 3 — Installation locale avec venv + pip (Python déjà installé)

> Alternative si vous préférez ne pas utiliser `uv`.

**Étape 1 — Prérequis**

Installez Python 3.11 depuis https://www.python.org/downloads/

**Étape 2 — Cloner le dépôt**

```shell
git clone https://github.com/harry0703/MoneyPrinterTurbo.git
cd MoneyPrinterTurbo
```

**Étape 3 — Créer et activer un environnement virtuel**

```shell
python3.11 -m venv .venv
```

Sur macOS / Linux :
```shell
source .venv/bin/activate
```

Sur Windows :
```powershell
.venv\Scripts\activate
```

**Étape 4 — Installer les dépendances**

```shell
pip install -r requirements.txt
```

**Étape 5 — Créer et configurer `config.toml`**

```shell
cp config.example.toml config.toml
```

Éditez `config.toml` avec vos clés API.

**Étape 6 — Lancer l'interface web**

Sur Windows :
```powershell
.\webui.bat
```

Sur macOS / Linux :
```shell
sh webui.sh
```

---

### Méthode 4 — Windows (package tout-en-un)

> La méthode la plus rapide pour tester sur Windows, sans installer Python.

1. Téléchargez le package v1.2.6 sur Google Drive : https://drive.google.com/file/d/1HsbzfT7XunkrCrHw5ncUjFX8XX4zAuUh/view?usp=sharing
2. Décompressez l'archive
3. Double-cliquez sur `update.bat` pour mettre à jour vers le dernier code
4. Double-cliquez sur `start.bat` pour lancer l'application
5. Le navigateur s'ouvre automatiquement (utilisez **Chrome** ou **Edge** en cas de page blanche)

---

### Méthode 5 — Google Colab (sans installation locale)

Testez MoneyPrinterTurbo directement dans le navigateur, sans rien installer :

[![Ouvrir dans Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/harry0703/MoneyPrinterTurbo/blob/main/docs/MoneyPrinterTurbo.ipynb)

---

## Configuration 🔧

### Fournisseurs LLM supportés

Modifiez `llm_provider` dans `config.toml` :

| Valeur        | Description                                |
|---------------|--------------------------------------------|
| `openai`      | OpenAI (GPT-4, GPT-3.5, etc.)              |
| `aihubmix`    | Passerelle multi-modèles (recommandé)       |
| `deepseek`    | DeepSeek (bon rapport qualité/prix)        |
| `gemini`      | Google Gemini                              |
| `ollama`      | Modèles locaux via Ollama                  |
| `azure`       | Azure OpenAI                               |
| `moonshot`    | Moonshot AI                                |
| `qwen`        | Alibaba Qwen                               |
| `minimax`     | MiniMax                                    |
| `ernie`       | Baidu ERNIE                                |
| `modelscope`  | ModelScope                                 |

### Sources de vidéos

| Source    | Inscription                                                           | Notes                              |
|-----------|-----------------------------------------------------------------------|------------------------------------|
| Pexels    | https://www.pexels.com/api/                                           | Gratuit, HD                        |
| Pixabay   | https://pixabay.com/api/docs/                                         | Gratuit, HD                        |
| Coverr    | https://coverr.co/developers?ctx=header_navigation                    | Gratuit (50 req/h), surtout 16:9   |

### Changer la langue de l'interface

Dans l'interface web, un sélecteur de langue est disponible en haut à droite. Sélectionnez **fr - Français** pour passer en français.

Vous pouvez aussi définir la langue par défaut dans `config.toml` :

```toml
[ui]
language = "fr"
```

---

## Synthèse vocale 🗣

La liste complète des voix disponibles : [Liste des voix](./docs/voice-list.txt)

Le fournisseur TTS par défaut est **Edge TTS** (gratuit, aucune clé API requise). Dans l'interface web, il apparaît sous le nom **"Azure TTS V1"**.

> **Remarque :** "Azure TTS V1" (Edge TTS, gratuit) et "Azure TTS V2" (Azure Speech SDK payant) sont deux options distinctes. Seul V2 nécessite une clé API Azure.

Pour utiliser les voix **Azure TTS V2** (plus naturelles), configurez vos identifiants Azure dans `config.toml` :

```toml
[azure]
speech_key = "votre-clé-azure-speech"
speech_region = "eastus"
```

---

## Génération des sous-titres 📜

Deux modes disponibles, à configurer via `subtitle_provider` dans `config.toml` :

| Mode      | Description                                                                                   | Avantages                         |
|-----------|-----------------------------------------------------------------------------------------------|-----------------------------------|
| `edge`    | Utilise les horodatages Edge TTS pour synchroniser les sous-titres                            | Rapide, sans GPU, fonctionne partout |
| `whisper` | Transcrit l'audio localement avec `faster-whisper` pour des sous-titres précis au mot près    | Précision maximale, plus lent      |

**Recommandation :** commencez avec le mode `edge`. Passez à `whisper` si la qualité est insuffisante.

### Téléchargement du modèle Whisper

Le modèle `whisper-large-v3` (~3 Go) est téléchargé automatiquement depuis HuggingFace.

Si le téléchargement échoue (connexion lente ou réseau restreint) :
- Baidu Netdisk : https://pan.baidu.com/s/11h3Q6tsDtjQKTjUu3sc5cA?pwd=xjs9
- Quark Netdisk : https://pan.quark.cn/s/3ee3d991d64b

Placez le dossier extrait dans `MoneyPrinterTurbo/models/` :

```
MoneyPrinterTurbo/
  └─ models/
      └─ whisper-large-v3/
             config.json
             model.bin
             preprocessor_config.json
             tokenizer.json
             vocabulary.json
```

---

## Musique de fond 🎵

Les fichiers de musique de fond se trouvent dans `resource/songs/`. Vous pouvez y ajouter vos propres fichiers `.mp3`.

> Les fichiers inclus par défaut proviennent de vidéos YouTube. En cas de problème de droits, supprimez-les.

---

## Polices de sous-titres 🅰

Les polices se trouvent dans `resource/fonts/`. Ajoutez vos propres fichiers `.ttf` ou `.ttc` pour les utiliser dans l'interface web.

---

## Questions fréquentes 🤔

### ❓ `RuntimeError: No ffmpeg exe could be found`

ffmpeg est normalement téléchargé automatiquement. Si ce n'est pas le cas :

1. Téléchargez ffmpeg depuis https://www.gyan.dev/ffmpeg/builds/
2. Décompressez et notez le chemin de `ffmpeg.exe`
3. Ajoutez dans `config.toml` :

```toml
[app]
# Adaptez selon votre chemin réel. Sur Windows, utilisez \\ comme séparateur
ffmpeg_path = "C:\\Users\\votre-nom\\Downloads\\ffmpeg.exe"
```

### ❓ `ImageMagick is not installed on your computer`

> **Cette erreur ne s'applique plus à la version actuelle.**
>
> Depuis la migration vers **MoviePy 2.x**, le rendu des sous-titres utilise **Pillow** et non ImageMagick. Si vous voyez cette erreur, mettez à jour le code avec `git pull` (ou `update.bat` sur Windows).

### ❓ `OSError: [Errno 24] Too many open files`

Le système a atteint sa limite de fichiers ouverts simultanément.

Vérifiez la limite actuelle :
```shell
ulimit -n
```

Augmentez-la temporairement :
```shell
ulimit -n 10240
```

### ❓ Échec du téléchargement du modèle Whisper

```
LocalEntryNotFoundError: Cannot find an appropriate cached snapshot folder...
```

ou

```
An error occurred while synchronizing the model Systran/faster-whisper-large-v3 from the Hugging Face Hub...
```

**Solution :** téléchargez le modèle manuellement depuis les liens Netdisk mentionnés dans la section [Génération des sous-titres](#génération-des-sous-titres-).

### ❓ L'interface s'affiche en blanc au démarrage

Utilisez **Chrome** ou **Edge**. Évitez Safari ou Firefox pour Streamlit.

### ❓ Permettre l'accès depuis d'autres appareils du réseau local

Sur Windows, avant de lancer `webui.bat` :
```cmd
set MPT_WEBUI_HOST=0.0.0.0
```

Sur macOS / Linux :
```shell
uv run streamlit run ./webui/Main.py --server.address=0.0.0.0
```

Puis accédez via `http://<IP-de-votre-machine>:8501` depuis un autre appareil.

---

## Remerciements 🙏

**RecCloud** (plateforme multimédia IA) propose un service de génération vidéo en ligne basé sur ce projet, sans déploiement requis :
- Version française/internationale : https://reccloud.com
- Version chinoise : https://reccloud.cn

**Picwish** (https://picwish.com) soutient et sponsorise ce projet pour en permettre la maintenance continue.

---

## Retours & Contributions 📢

- Signalez un bug ou proposez une amélioration : [Issues](https://github.com/harry0703/MoneyPrinterTurbo/issues)
- Contribuez au code : [Pull Requests](https://github.com/harry0703/MoneyPrinterTurbo/pulls)

## Licence 📝

Voir le fichier [`LICENSE`](LICENSE)

## Historique des étoiles

[![Star History Chart](https://api.star-history.com/svg?repos=harry0703/MoneyPrinterTurbo&type=Date)](https://star-history.com/#harry0703/MoneyPrinterTurbo&Date)
