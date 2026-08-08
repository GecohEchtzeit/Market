# GECOH MARKET V1

Enthalten:
- Home + Marketplace
- Suche/Kategorien
- Produktseiten
- Registrierung/Login
- Buyer Dashboard
- Seller Dashboard
- Produkt erstellen
- Digitalen Stock/Keys hochladen
- 5% Plattformgebühr
- Pending Orders
- Admin-Statistik
- Neon/PostgreSQL-ready
- Mobile Dark Design

Wichtig: V1 verarbeitet noch keine Zahlungen. Nur legale digitale Produkte/Services.

## Start
export SECRET_KEY="DEIN_LANGES_SECRET"
export DATABASE_URL="postgresql://..."
pip install -r requirements.txt
python app.py

Dann: http://SERVER-IP:8080

## Produktion
gunicorn -w 2 -b 127.0.0.1:8080 app:app
