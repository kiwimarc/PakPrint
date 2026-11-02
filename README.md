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

## Adgang overalt med Tailscale (anbefalet)

Uden Tailscale virker PakPrint kun, når telefonen er på samme Wi-Fi som computeren. Med Tailscale virker den overalt, også på mobildata, uden at åbne noget i routeren. Kun dine egne enheder kan se appen. Tailscale er gratis til privat brug.

### 1. Installer Tailscale på computeren

1. Hent Tailscale fra [tailscale.com/download](https://tailscale.com/download), og installer det.
2. Klik på Tailscale-ikonet ved uret, og log ind (fx med en Google- eller Microsoft-konto).
3. **Windows:** slå **Run unattended** til i Tailscale-menuen (under Preferences). Så kører Tailscale videre, også når du ikke er logget ind på Windows.

### 2. Installer Tailscale på telefonen

1. Hent Tailscale fra Google Play eller App Store.
2. Log ind med **samme konto** som på computeren, og slå forbindelsen til.

Telefonen og computeren er nu på dit eget private netværk ("tailnet").

### 3. Giv PakPrint en fast https-adresse (Tailscale Serve)

Start PakPrint som normalt (`python app.py`). Kør derefter i et andet terminalvindue:

```powershell
tailscale serve --bg 5000
```

Første gang åbner Tailscale en side i browseren, hvor du skal godkende HTTPS for dit tailnet. Godkend, og kør kommandoen igen.

Kommandoen viser din adresse, fx:

```
https://produktion-pc.tail1234.ts.net
```

`--bg` betyder, at det kører videre i baggrunden, også efter genstart. Du skal kun gøre det én gang.

### 4. Gem den på telefonen

Åbn adressen i Chrome eller Safari på telefonen, log ind med `APP_PASSWORD`, og vælg **Føj til hjemmeskærm**.

### 5. (Valgfrit) Gør appen usynlig på dit Wi-Fi

Når du bruger Tailscale Serve, behøver appen ikke at være synlig for andre på netværket. Sæt i `.env`:

```
HOST=127.0.0.1
```

Så kan appen kun nås gennem Tailscale-adressen.

### Nyttige kommandoer

```powershell
tailscale serve status   # vis hvad der deles, og på hvilken adresse
tailscale serve reset    # stop delingen
```

> Brug **ikke** `tailscale funnel`. Den gør appen offentlig på internettet for alle.

### Husk

* Computeren skal være tændt og må ikke gå i dvale, og PakPrint skal køre.
* Tailscale skal være slået til på telefonen, når du vil printe.

---

## Fejlfinding

**Telefonen viser `ERR_TOO_MANY_RETRIES`, og der kommer intet i loggen (Android 17, fx Pixel)**
Android 17 blokerer apps fra det lokale netværk, til de får lov. Gå til *Indstillinger → Apps → Chrome → Tilladelser → Enheder i nærheden → Tillad*. Gør det samme for andre browsere. Kan også ske via Tailscale.

**Virker på computeren, men ikke fra telefonen på samme Wi-Fi (Windows)**
* Netværket skal stå som *Privat*: Indstillinger → Netværk og internet → Wi-Fi.
* Åbn porten i PowerShell som administrator:
  `New-NetFirewallRule -DisplayName "PakPrint" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow -Profile Private`
* Telefonen skal være på samme Wi-Fi og ikke på et gæstenet.
* Skriv `http://` foran adressen.

**Tjek om appen lytter**
`netstat -ano | findstr :5000` skal vise `LISTENING`.

**Gunicorn virker ikke på Windows**
Brug `python app.py`, eller `pip install waitress` og `waitress-serve --listen=0.0.0.0:5000 app:app`.

---

## Teknisk

* Python / Flask, PDF med `fpdf2` (laves i hukommelsen – intet gemmes på disk).
* Dinero API v1, personlig integration (OAuth2 password grant). Token genbruges i op til en time, så appen holder sig langt under Dineros grænse på 60 kald i minuttet.
* Layoutet tilpasses i `build_delivery_note_pdf()`.

## Licens

MIT.
