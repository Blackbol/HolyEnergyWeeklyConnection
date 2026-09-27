# ⚡ Holy Energy — Connexion Hebdomadaire Automatique

Automatise la connexion hebdomadaire à [fr.holy.com](https://fr.holy.com) pour remporter **25 HOLY Coins par semaine** (soit 1300 coins par an) sans aucune intervention manuelle récurrente.

---

## 🌟 Points Forts & Nouveautés (v0.2.0)

- 🔄 **Cookie Roulant Persistant (Rolling Cookie) :** Sauvegarde automatique du cookie rafraîchi par Shopify dans `data/cookie.txt` après chaque visite réussie pour prolonger la session indéfiniment.
- 🛡️ **Anti-AdBlock & Résilience DNS :** Résolution DNS-over-HTTPS (DoH) intégrée (Cloudflare/Google) pour éviter que les ad-blockers réseau (Pi-hole, AdGuard, box internet) ne bloquent l'API `sdk.loyaltylion.net`.
- 🐳 **Déploiement Simplifié au Choix :**
  - **Option 1 (Recommandée) :** Démon autonome en 1 seul conteneur Docker avec planificateur intégré (Europe/Paris).
  - **Option 2 :** Compatible Ofelia pour NAS (Synology, QNAP, Unraid).
  - **Option 3 :** CLI local pour cron système Linux.
- 🔔 **Notifications Multi-Canaux :** Alertes instantanées sur Discord (Webhook), Telegram (Bot) ou smartphone via [ntfy.sh](https://ntfy.sh) (succès avec solde total ou alerte si cookie expiré).
- 🧪 **Validation Stricte & Sécurité :** Finis les faux positifs ! Le script vérifie la présence effective du token client avant d'enregistrer le cookie ou de crier victoire.

---

## 🚀 Démarrage Rapide

### 1. Extraire votre cookie de session (1 minute)

1. Connectez-vous sur [fr.holy.com](https://fr.holy.com) dans votre navigateur (Chrome, Brave, Firefox, Edge).
2. Appuyez sur **F12** pour ouvrir les Outils de Développement.
3. Allez dans l'onglet **Application** (Chrome/Brave) ou **Stockage** (Firefox).
4. Déroulez **Cookies** dans le menu de gauche et cliquez sur `https://fr.holy.com`.
5. Repérez la ligne dont le nom est `_shopify_essential`.
6. Double-cliquez sur sa valeur et copiez-la en entier (chaîne commençant par `:AZ...`).

### 2. Configurer `.env`

Copiez l'exemple et collez vos informations :

```bash
cp .env.example .env
```

Éditez le fichier `.env` :

```env
HOLY_SHOPIFY_COOKIE=:AZ...collez_ici_la_valeur_complete...
HOLY_EMAIL=votre.email@exemple.com
LOG_LEVEL=PROD
```

### 3. Tester immédiatement

```bash
# Vérifier la validité du cookie sans créditer
holy-connect verify

# Ou exécuter la connexion hebdomadaire
holy-connect run
```

---

## 🐳 Déploiement avec Docker Compose

### Option A : Démon Autonome (Recommandé)

Aucun outil tiers requis. Le conteneur reste actif, consomme moins de 25 Mo de RAM, et se lance chaque **lundi à 08h00**.

1. Créez un dossier et récupérez les fichiers :
   ```bash
   mkdir holy-energy && cd holy-energy
   curl -O https://raw.githubusercontent.com/Blackbol/HolyEnergyWeeklyConnection/main/docker-compose.yml
   curl -O https://raw.githubusercontent.com/Blackbol/HolyEnergyWeeklyConnection/main/.env.example
   cp .env.example .env
   # Renseignez .env avec votre cookie
   ```

2. Lancez le conteneur en arrière-plan :
   ```bash
   docker compose up -d
   ```

3. Vérifiez les logs :
   ```bash
   docker compose logs -f holy-energy
   ```

### Option B : Déploiement avec Ofelia (pour NAS Synology / QNAP)

Si vous utilisez déjà Ofelia comme orchestrateur cron sur votre NAS :

1. Ouvrez `docker-compose.yml` et décommentez le bloc `ofelia`.
2. Lancez :
   ```bash
   docker compose up -d
   ```

---

## 🛠️ Commandes CLI (`holy-connect`)

Le paquet fournit un outil en ligne de commande complet :

| Commande | Description |
|---|---|
| `holy-connect run` | Exécute la connexion hebdomadaire et réclame les 25 points *(défaut)* |
| `holy-connect verify` | Teste la validité du cookie actuel et affiche le solde sans créditer |
| `holy-connect daemon` | Démarre la boucle d'exécution planifiée en arrière-plan |
| `holy-connect set-cookie <COOKIE>` | Enregistre un nouveau cookie dans `data/cookie.txt` et le teste immédiatement |
| `holy-connect login` | *(Optionnel)* Ouvre un navigateur avec Playwright pour capturer le cookie automatiquement |

---

## ⚙️ Variables d'Environnement

| Variable | Obligatoire | Valeur par défaut | Description |
|---|:---:|:---:|---|
| `HOLY_SHOPIFY_COOKIE` | **Oui** | — | Cookie `_shopify_essential` extrait du navigateur |
| `HOLY_EMAIL` | Non | `""` | Email du compte (utilisé pour les logs et notifications) |
| `HOLY_SCHEDULE_DAY` | Non | `monday` | Jour d'exécution (`monday`, `tuesday`, ..., `sunday`) |
| `HOLY_SCHEDULE_TIME` | Non | `08:00` | Heure d'exécution planifiée (format 24h `HH:MM`) |
| `HOLY_RUN_ON_STARTUP` | Non | `true` | Exécuter une connexion immédiate dès le démarrage du conteneur |
| `HOLY_COOKIE_FILE` | Non | `data/cookie.txt` | Chemin du fichier où est persisté le cookie roulant |
| `HOLY_TIMEOUT` | Non | `30` | Timeout des requêtes HTTP (secondes) |
| `LOG_LEVEL` | Non | `PROD` | Niveau de log : `PROD` (concis), `INFO` (détaillé), `DEBUG` |
| `TZ` | Non | `Europe/Paris` | Fuseau horaire pour la planification |
| `DISCORD_WEBHOOK_URL` | Non | — | URL d'un webhook Discord pour recevoir les alertes |
| `TELEGRAM_BOT_TOKEN` | Non | — | Token d'un bot Telegram |
| `TELEGRAM_CHAT_ID` | Non | — | ID du chat Telegram destinataire |
| `NTFY_TOPIC` | Non | — | Nom du topic [ntfy.sh](https://ntfy.sh) pour notifications mobiles |

---

## 🔔 Exemple de Sorties

### En mode standard (`LOG_LEVEL=PROD`) :
```text
Connexion au site Holy Energy en cours (votre.email@exemple.com)...
25 points crédités — Balance totale : 425 points
```

### Si les points ont déjà été crédités cette semaine :
```text
Connexion au site Holy Energy en cours (votre.email@exemple.com)...
Points déjà crédités cette semaine — Balance totale : 425 points
```

---

## 💻 Développement & Tests

```bash
# Cloner le projet
git clone https://github.com/Blackbol/HolyEnergyWeeklyConnection.git
cd HolyEnergyWeeklyConnection

# Environnement virtuel
python3 -m venv venv
source venv/bin/activate

# Installation des dépendances de dev
pip install -r requirements-dev.txt
pip install -e .

# Lancer la suite de tests
pytest

# Linter et vérification des types
ruff check src/ tests/
mypy src/ tests/
```

---

## 📄 Licence

Projet personnel sous licence MIT. Holy Energy et HOLY Coins sont des marques déposées de Holy Energy GmbH.
