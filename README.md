# PakPrint

**Udskriv følgesedler fra Dinero direkte på mobilen – uden PC og uden overstregningstusch.**

PakPrint henter dine seneste fakturaer og kladder via Dineros API og laver en printklar følgeseddel-PDF uden priser med ét tryk.

## Funktioner

* Mobilvenlig og kan gemmes på hjemmeskærmen, så den føles som en app.
* Følgesedlen viser modtager, adresse, fakturanr., dato, varelinjer, antal og enhed – ingen priser.
* Virker også på kladder, så du kan pakke og printe, før fakturaen er bogført.
* Felt til dato og kundens underskrift nederst.
* Beskyttet med adgangskode.

---

## Opsætning

### 1. Skaf adgang til Dinero (én gang)

Kræver Dinero **Pro** eller **Total**.

1. Log ind på Dinero på en computer.
2. Gå til **Indstillinger → Integrationer → Se og opret API-nøgler → Personlig integration** og ansøg.
3. Når den er godkendt (typisk inden for en arbejdsdag), får du vist **Client ID** og **Client Secret**. De vises kun én gang, så gem dem med det samme.
4. Opret en **API-nøgle** samme sted, i den virksomhed du vil hente fakturaer fra.
5. Find dit **firma-ID** nederst til venstre i Dinero.

### 2. Installer

```bash
cd pakprint
python -m venv .venv
# Windows: .venv\Scripts\activate    Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Konfigurer

Kopiér `example.env` til `.env` og udfyld værdierne. Lav en `SECRET_KEY` med:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 4. Test forbindelsen

```bash
python app.py demo    # laver demo_foelgeseddel.pdf uden at kalde Dinero (tjek layout)
python app.py check   # tjekker login, adgang til virksomheden og bygger en rigtig følgeseddel
```

`check` fortæller præcis, hvad der er galt, hvis noget ikke virker.

### 5. Start

```bash
python app.py
```

Appen kører på `http://<computerens-ip>:5000`.

---

## Hvor skal den køre?

**A) I produktionslokalet (anbefalet, simplest og sikrest).**
En Raspberry Pi eller gammel PC på samme Wi-Fi som printeren. Telefonen når appen, når den er på Wi-Fi'et – og det er jo der, printeren står. Intet er synligt fra internettet.

**B) I skyen** (fx Render, Fly.io eller en VPS) hvis du vil kunne åbne den overalt. Brug **altid HTTPS** og en stærk `APP_PASSWORD`, da appen viser dine kunders navne og adresser.

### Docker

```bash
docker build -t pakprint .
docker run -d -p 5000:5000 --env-file .env --name pakprint --restart unless-stopped pakprint
```

---

## Brug i hverdagen

1. Åbn adressen i **Safari** (iPhone) eller **Chrome** (Android) og log ind.
2. Tryk **Del → Føj til hjemmeskærm**.
3. Lav fakturaen i Dinero-appen som normalt.
4. Åbn PakPrint, tryk på ordren, og tryk **Del → Udskriv** (iPhone) eller **Udskriv** (Android) i PDF-visningen.

Printeren skal kunne modtage print fra telefonen (AirPrint på iPhone, Mopria eller producentens app på Android).

---

## Teknisk

* Python / Flask, PDF med `fpdf2` (laves i hukommelsen – intet gemmes på disk).
* Dinero API v1, personlig integration (OAuth2 password grant). Token genbruges i op til en time, så appen holder sig langt under Dineros grænse på 60 kald i minuttet.
* Layoutet tilpasses i `build_delivery_note_pdf()`.

## Licens

MIT.
