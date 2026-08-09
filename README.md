# GECOH MARKET V3 — automatische LTC-Zahlungen

Neu:
- LTC-only BTCPay Checkout
- automatische LTC Deposit-Invoices
- verifizierte BTCPay-Webhooks
- `InvoiceSettled` schreibt Wallet-Deposit automatisch gut
- Marketplace-Kauf erstellt automatisch eine BTCPay-Rechnung
- Nach bestätigter Zahlung wird genau ein Stock-Item ausgeliefert
- Seller-Balance wird nach 5% Plattformgebühr automatisch gutgeschrieben
- abgelaufene/ungültige Invoices markieren Orders als fehlgeschlagen
- Withdrawals bleiben als Admin-Freigabe

## Environment
Siehe `.env.example`.

## BTCPay
1. BTCPay Server mit Litecoin betreiben.
2. Store erstellen und Litecoin im Store aktivieren.
3. Greenfield API-Key mit nur den benötigten Invoice-Rechten erstellen.
4. Webhook auf `https://gecohmarket.de/webhooks/btcpay` setzen.
5. Webhook-Secret in `BTCPAY_WEBHOOK_SECRET` speichern.

## Sicherheit
Die Flask-App speichert keine Litecoin-Private-Keys. BTCPay übernimmt Rechnungserstellung und Blockchain-Erkennung.
