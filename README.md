# Holy Energy — Connexion Hebdomadaire Automatique

Automatise la connexion hebdomadaire à [fr.holy.com](https://fr.holy.com) pour gagner **25 HOLY Coins** par semaine sans aucune intervention manuelle.

## Comment ça marche

Le script visite la page compte de Holy Energy en utilisant un cookie de session sauvegardé, puis appelle directement l'API LoyaltyLion pour créditer les points de fidélité — exactement ce que ferait un navigateur.

**Prérequis :** Une seule action manuelle au départ (extraire le cookie depuis ton navigateur), puis tout est automatique pendant **1 an**.

---

## Démarrage rapide

### 1. Récupérer le cookie de session

1. Connecte-toi à [fr.holy.com](https://fr.holy.com) dans ton navigateur (Chrome, Brave ou Firefox)
2. Appuie sur **F12** pour ouvrir les DevTools
3. Va dans l'onglet **Application** → **Storage** → **Cookies** → `https://fr.holy.com`
4. Trouve la ligne `_shopify_essential`
5. Copie la colonne **Value** en entier (commence par `:AZ68...`, très longue chaîne)

### 2. Créer le fichier `.env`

Copie `.env.example` en `.env` et remplis tes informations :

```bash
cp .env.example .env
```

```env
HOLY_EMAIL=ton.email@exemple.com
HOLY_PASSWORD=ton_mot_de_passe
HOLY_SHOPIFY_COOKIE=:AZ68...colle_la_valeur_complete_ici...
LOG_LEVEL=PROD
```

---

## Déploiement avec Docker Compose (recommandé pour NAS)

C'est la méthode recommandée pour un NAS (Synology, QNAP, etc.). Le container se lance automatiquement chaque lundi à 08h00.

### 1. Télécharger les fichiers nécessaires

```bash
mkdir holy-energy && cd holy-energy
curl -O https://raw.githubusercontent.com/Blackbol/HolyEnergyWeeklyConnection/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/Blackbol/HolyEnergyWeeklyConnection/main/.env.example
```

### 2. Configurer

```bash
cp .env.example .env
# Édite .env avec tes informations
```

### 3. Créer le `docker-compose.yml`

Crée un fichier `docker-compose.yml` avec ce contenu :

```yaml
services:

  holy-energy:
    image: ghcr.io/blackbol/holyenergyweeklyconnection:latest
    container_name: holy-energy
    environment:
      - HOLY_EMAIL=${HOLY_EMAIL}
      - HOLY_PASSWORD=${HOLY_PASSWORD}
      - HOLY_SHOPIFY_COOKIE=${HOLY_SHOPIFY_COOKIE}
      - HOLY_TIMEOUT=${HOLY_TIMEOUT:-30}
      - LOG_LEVEL=${LOG_LEVEL:-PROD}
      - TZ=Europe/Paris
    dns:
      - 8.8.8.8
      - 1.1.1.1
    # restart: unless-stopped  # Désactivé — lancé uniquement par ofelia chaque lundi

  ofelia:
    image: mcuadros/ofelia:latest
    container_name: ofelia
    depends_on:
      - holy-energy
    command: daemon --docker -f label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}
    labels:
      ofelia.job-run.weekly-connection.schedule: "0 8 * * 1"   # lundi 08:00
      ofelia.job-run.weekly-connection.container: "holy-energy"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    restart: unless-stopped
```

### 4. Démarrer

```bash
docker compose up -d
```

Ofelia tourne en permanence et lance le script chaque lundi à 08h00. Le container Holy Energy démarre, exécute le script, puis s'arrête tout seul.

### Vérifier les logs

```bash
docker compose logs ofelia
```

### Tester immédiatement sans attendre lundi

```bash
docker run --rm --env-file .env ghcr.io/blackbol/holyenergyweeklyconnection:latest
```

---

## Déploiement avec Docker uniquement

Si tu préfères gérer le scheduling toi-même (cron du NAS, planificateur de tâches, etc.) :

```bash
docker run --rm --env-file .env ghcr.io/blackbol/holyenergyweeklyconnection:latest
```

Lance cette commande chaque lundi matin depuis le planificateur de tâches de ton NAS.

---

## Variables d'environnement

| Variable | Obligatoire | Description |
|----------|-------------|-------------|
| `HOLY_EMAIL` | Oui | Adresse email du compte Holy Energy |
| `HOLY_PASSWORD` | Oui | Mot de passe du compte |
| `HOLY_SHOPIFY_COOKIE` | Oui | Cookie `_shopify_essential` extrait du navigateur (valide 1 an) |
| `HOLY_TIMEOUT` | Non | Timeout des requêtes HTTP en secondes (défaut : `30`) |
| `LOG_LEVEL` | Non | `PROD` (messages lisibles), `INFO` (technique), `DEBUG` (tout) — défaut : `INFO` |

### Exemple de sortie avec `LOG_LEVEL=PROD`

```
Connexion au site Holy Energy en cours (ton.email@exemple.com)...
25 points credites — Balance totale : 350 points
```

Ou, si les points ont déjà été crédités cette semaine :

```
Connexion au site Holy Energy en cours (ton.email@exemple.com)...
Points deja credites cette semaine — Balance totale : 350 points
```

---

## Renouvellement annuel du cookie

Le cookie expire après **1 an**. Quand le script affiche :

```
Authentication failed: Session cookie has expired or is invalid.
```

Il suffit de répéter l'étape 1 (extraire un nouveau cookie depuis le navigateur) et de mettre à jour `HOLY_SHOPIFY_COOKIE` dans `.env`.

---

## Construction depuis les sources

```bash
git clone https://github.com/Blackbol/HolyEnergyWeeklyConnection.git
cd holy-energy-weekly-connection

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e .

cp .env.example .env
# Édite .env

python -m holy_energy_weekly_connection
```

Pour build l'image Docker localement :

```bash
docker build -t holy-energy-weekly .
docker run --rm --env-file .env holy-energy-weekly
```
