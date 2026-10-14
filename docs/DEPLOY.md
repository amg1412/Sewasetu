# Deploying (any Ubuntu VPS, no domain needed)

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
git clone <your private repo> sewasetu && cd sewasetu
mkdir -p seed logs && cp /path/to/seed.sql seed/seed.sql     # the data is not in git
cp .env.example .env && nano .env                            # set unique SS_SECRET_KEY, SS_ADMIN_PASSWORD and POSTGRES_PASSWORD
sudo docker compose up -d --build                            # all services restart on reboot
```
Open TCP port 8000 in the VPS firewall. The URL is `http://<server-ip>:8000`.

Fresh database volume: `schema.sql` already contains the new indexes and column width.
Existing database: `psql ... -f app/migrations/001_indexes.sql -f app/migrations/002_password_hash_width.sql`.

Check it works:
```bash
curl -I http://<ip>:8000/                       # 200
sudo docker compose exec app python scripts/deemed_approval.py --dry-run
sudo docker compose logs -f app
```
Hand the assessor the admin username/password from `.env`. Keep the server up until they confirm.
