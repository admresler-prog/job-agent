"""Jobs.cz, Prace.cz, StartupJobs: QA, data a prompty. Python 3.9+, requests, beautifulsoup4."""
import json
import os
import re
import shutil
import tempfile
import time
import unicodedata
from html import escape
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, quote, urlunparse

import requests
from bs4 import BeautifulSoup

URL = "https://www.jobs.cz/prace/"
SOUBOR = Path(__file__).with_name("inzeraty.json")
HLEDANI = ["junior tester", "QA tester home office", "software tester Brno",
           "software tester Olomouc", "software tester Hradec Králové",
           "manual tester", "junior data analyst", "datový analytik junior", "data analyst home office", "junior BI analyst", "junior SQL analytik", "Prompt Engineer", "AI Prompt Engineer",
           "prompt engineering"]
MESTA = ["Brno", "Olomouc", "Hradec Králové"]
MAX_STRAN = 3
POKUSY = 3
TIMEOUT = (10, 35)  # připojení, čekání na data; nejde o celkový čas běhu
VERZE = 4
OBNOVA_HODIN = 24


def normal(text):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", text.lower())
                            if not unicodedata.combining(c)).split())


def kategorie(nazev):
    t = normal(nazev)
    if re.search(r"\b(senior|sr|medior|lead|principal|head|manager|garant)\b", t):
        return None
    if re.search(r"\bprompt\s+(engineer\w*|specialist\w*|inzenyr\w*)\b", t):
        return "Prompt Engineer"
    if re.search(r"\b(data analyst|data analytics|datovy analytik|datova analyticka|business intelligence analyst|bi analyst|sql analytik)\b", t):
        return "Datový analytik"
    if re.search(r"\b(support|podpora|vyroba|elektro|hardware|laborator|quality manager)\w*\b", t):
        return None
    if re.search(r"\b(tester\w*|qa|testing|testovani)\b", t):
        return "QA tester"
    return None


def ohodnot(nazev, text, typ):
    t, n = normal(text), normal(nazev)
    skore, duvody = 45, []

    def body(pocet, duvod):
        nonlocal skore
        skore += pocet
        duvody.append(f"{pocet:+d}: {duvod}")

    junior = bool(re.search(r"\b(junior|jr|trainee)\b", n))
    if junior:
        body(20, "Juniorská pozice v názvu")
    if re.search(r"bez (predchozi )?praxe|vhodn\w* pro absolvent|absolvent\w* vitan|zaucime", t):
        body(15, "Text výslovně připouští začátečníky")
        junior = True
    if not junior:
        duvody.append("Juniorská úroveň není potvrzena – ověř požadavky.")
    if re.search(r"bez (moznosti )?(home office|prace z domova)|home office (neni|neumozn)|no remote", t):
        duvody.append("Text uvádí omezení práce z domova.")
    elif re.search(r"home office|prace z domova|praci z domova|\bremote\b", t):
        body(10, "Zmíněna práce z domova; rozsah ověř v nabídce")
    mesta = [m for m in MESTA if re.search(r"\b" + re.escape(normal(m)) + r"\b", t)]
    if mesta:
        body(5, "Zmíněná preferovaná lokalita: " + ", ".join(mesta))
    if re.search(r"(?:[3-9]|1\d)\s*\+?\s*(?:roky|roku|let|years).{0,30}(?:praxe|zkusen|experience)", t):
        body(-25, "Zmíněny alespoň tři roky zkušeností; ověř, zda jsou povinné")
    if re.search(r"anglictin\w*.{0,25}(pokrocil|plynul|c1|c2)|fluent english|advanced english", t):
        body(-10, "Zmíněna pokročilá angličtina (zachována původní preference)")
    if typ == "QA tester":
        if re.search(r"manual\w*|rucni test", t):
            body(10, "Manuální testování")
        if re.search(r"automat\w*|sdet", n):
            body(-20, "Hlavní zaměření na automatizaci")
        if re.search(r"testovac\w* scenar|bug report|test case|postman", t):
            body(5, "Konkrétní QA činnosti nebo nástroje")
    elif typ == "Datový analytik":
        if re.search(r"\b(sql|excel|power bi|tableau|python)\b", t):
            body(10, "Zmíněny analytické nástroje")
        if re.search(r"analyz|reporting|dashboard|datov\w* model", t):
            body(5, "Analytické činnosti v popisu")
    elif typ == "Datový analytik":
        if re.search(r"\bsql\b", t):
            body(10, "Práce s SQL")
        if re.search(r"power bi|excel|tableau", t):
            body(10, "Analytické nástroje")
        if re.search(r"\bpython\b|reporting|dashboard", t):
            body(5, "Python nebo reporting")
    else:
        if re.search(r"prompt\w*", t):
            body(10, "Práce s prompty potvrzena v popisu")
        if re.search(r"\b(llm|chatgpt|gpt|claude)\b|jazykov\w* model", t):
            body(5, "Práce s jazykovými modely")
        if re.search(r"evaluat|evaluac|hodnoceni vystupu|testovani prompt", t):
            body(5, "Vyhodnocování výstupů nebo promptů")
        if re.search(r"fine.tun|pytorch|tensorflow|trenovani model", t):
            body(-10, "Zmíněn vývoj nebo trénování modelů; ověř náročnost")
    return max(0, min(100, skore)), duvody


def stahni(session, adresa, params=None):
    for pokus in range(POKUSY):
        time.sleep(1)
        try:
            r = session.get(adresa, params=params, timeout=TIMEOUT)
            if r.status_code in (429, 500, 502, 503, 504):
                if pokus + 1 < POKUSY:
                    delay = r.headers.get("Retry-After", "")
                    if delay and (not delay.isdigit() or int(delay) > 60):
                        print("Server žádá delší pauzu; tuto adresu nyní přeskočím.")
                        return None
                    time.sleep(max(2 ** (pokus + 1), int(delay or 0)))
                    continue
            r.raise_for_status()
            return BeautifulSoup(r.content, "html.parser")
        except (requests.Timeout, requests.ConnectionError) as e:
            print(f"Pokus {pokus + 1}/{POKUSY}: {type(e).__name__}")
            if pokus + 1 < POKUSY:
                time.sleep(2 ** (pokus + 1))
        except requests.RequestException as e:
            print(f"Nelze načíst {adresa}: {e}")
            return None
    print("Adresa přeskočena; další nabídky se budou zpracovávat.")
    return None


def odkazy(soup):
    nalezene = {}
    for a in soup.find_all("a", href=True):
        u = urlparse(urljoin(URL, a["href"]))
        match = re.fullmatch(r"/rpd/(\d+)/?", u.path)
        if u.hostname not in ("jobs.cz", "www.jobs.cz") or not match:
            continue
        h = a.find(["h2", "h3"]) or a
        nazev = h.get_text(" ", strip=True)
        typ = kategorie(nazev)
        if typ:
            ident = match.group(1)
            nalezene[ident] = {"nazev": nazev, "odkaz": f"https://www.jobs.cz/rpd/{ident}/",
                               "kategorie": typ}
    return nalezene



# Další veřejné portály. Jejich HTML se může změnit nebo být omezené.
# Používáme pouze skutečné odkazy na doméně portálu, nikoliv domnělé inzeráty.
PORTALY = [
    ("Prace.cz", "https://www.prace.cz/hledat/", "prace.cz"),
    ("StartupJobs.cz", "https://www.startupjobs.cz/nabidky", "startupjobs.cz"),
]
PORTAL_DOTAZY = ["junior tester", "QA tester", "datový analytik", "data analyst", "prompt engineer"]

def portal_odkazy(soup, base, domena, portal):
    nalezene = {}
    for a in soup.find_all("a", href=True):
        u = urlparse(urljoin(base, a["href"]))
        host = (u.hostname or "").lower()
        if host not in (domena, "www." + domena) or u.scheme != "https":
            continue
        cesta = u.path.rstrip("/")
        if domena == "prace.cz":
            # Inzeráty Prace.cz mají typicky URL /nabidka/<id>.
            if not re.search(r"/nabidka/[^/]+", cesta):
                continue
        elif domena == "startupjobs.cz":
            # Nabídky StartupJobs: /nabidka/<slug-or-id>.
            if not re.search(r"/nabidka/[^/]+", cesta):
                continue
        h = a.find(["h2", "h3", "h4"]) or a
        nazev = h.get_text(" ", strip=True)
        if len(nazev) < 5 or len(nazev) > 160:
            continue
        typ = kategorie(nazev)
        if not typ:
            continue
        url = urlunparse((u.scheme, u.netloc, cesta + "/" if u.path.endswith("/") else cesta, "", "", ""))
        ident = portal + ":" + url
        nalezene[ident] = {"nazev": nazev, "odkaz": url, "kategorie": typ, "portal": portal}
    return nalezene


def prohledej_portaly(session):
    vse = {}
    for portal, base, domena in PORTALY:
        for dotaz in PORTAL_DOTAZY:
            print(f"Hledám na {portal}: {dotaz}")
            # Portály nemusí podporovat stejné parametry; při neúspěchu je přeskočíme.
            params = {"q": dotaz} if domena == "prace.cz" else {"search": dotaz}
            soup = stahni(session, base, params)
            if soup is not None:
                polozky = portal_odkazy(soup, base, domena, portal)
                print(f"  Nalezeno kandidátů: {len(polozky)}")
                vse.update(polozky)
    return vse

def detail(soup):
    # Strukturovaný popis vylučuje menu, doporučené inzeráty a globální filtry.
    def jobs(obj):
        if isinstance(obj, dict):
            typ = obj.get("@type", [])
            if typ == "JobPosting" or isinstance(typ, list) and "JobPosting" in typ:
                yield obj
            for value in obj.values():
                yield from jobs(value)
        elif isinstance(obj, list):
            for value in obj:
                yield from jobs(value)

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        for job in jobs(data):
            if job.get("description"):
                popis = BeautifulSoup(job["description"], "html.parser").get_text(" ", strip=True)
                misto = json.dumps(job.get("jobLocation", {}), ensure_ascii=False)
                remote = " remote" if job.get("jobLocationType") == "TELECOMMUTE" else ""
                return popis + " " + misto + remote
    el = soup.select_one('[data-test="jd-body-richtext"], [itemprop="description"], [data-test="job-description"], .job-description')
    if not el:
        return None
    info = soup.select('[data-test="jd-info-item"], [data-test="jd-info-location"]')
    return el.get_text(" ", strip=True) + " " + " ".join(x.get_text(" ", strip=True) for x in info)


def nacti_pamet(path):
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or any(not isinstance(v, dict) for v in data.values()):
        raise ValueError("Paměť musí být slovník ID → záznam. Soubor nebude přepsán.")
    return data


def firemni_detail(session, soup, ident):
    """Veřejný detail z téhož widgetu, který používá firemní stránka."""
    config = None
    for script in soup.find_all("script"):
        match = re.search(r'__LMC_CAREER_WIDGET__\.push\((\{.*?\})\);', script.get_text(), re.S)
        if match:
            try:
                config = json.loads(match.group(1))
            except ValueError:
                continue
            break
    if not config or not config.get("apiKey") or not config.get("widgetId"):
        return None
    query = """query Detail($widgetId: ID!, $jobAdId: ID!) {
      widget(id: $widgetId) { jobAd(id: $jobAdId) {
        id title content { htmlContent sections { title text } }
        suitableForGraduate locations { city }
      } }
    }"""
    for pokus in range(POKUSY):
        time.sleep(1 + 2 * pokus)
        try:
            r = session.post("https://api.capybara.lmc.cz/api/graphql/widget",
                headers={"X-Api-Key": config["apiKey"]},
                json={"query": query, "variables": {"widgetId": config["widgetId"], "jobAdId": ident}},
                timeout=TIMEOUT)
            if r.status_code == 429:
                print("Firemní detail: server omezuje požadavky, zkusím příště.")
                return None
            if r.status_code in (500, 502, 503, 504):
                continue
            r.raise_for_status()
            data = r.json()
            job = ((data.get("data") or {}).get("widget") or {}).get("jobAd")
            if data.get("errors") or not job or str(job.get("id")) != ident:
                return None
            content = job.get("content") or {}
            chunks = [content.get("htmlContent") or ""]
            chunks += [str(s.get("title") or "") + " " + str(s.get("text") or "")
                       for s in content.get("sections") or []]
            text = BeautifulSoup(" ".join(chunks), "html.parser").get_text(" ", strip=True)
            if not text:
                return None
            if job.get("suitableForGraduate"):
                text += " Vhodné pro absolventy."
            text += " " + " ".join(str(x.get("city") or "") for x in job.get("locations") or [])
            return text
        except (requests.Timeout, requests.ConnectionError):
            continue
        except (requests.RequestException, ValueError, TypeError):
            return None
    return None


def uloz_pamet(path, data):
    # Záloha předchozího platného souboru a atomická výměna ve stejné složce.
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as f:
            temp = Path(f.name)
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            shutil.copy2(path, path.with_suffix(".json.bak"))
        os.replace(temp, path)
    finally:
        if temp and temp.exists():
            temp.unlink()


def cerstvy(zaznam):
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(zaznam["zkontrolovano"])).total_seconds()
        return zaznam.get("verze_hodnoceni") == VERZE and 0 <= age < OBNOVA_HODIN * 3600
    except (KeyError, ValueError, TypeError):
        return False


def vytvor_report(vysledky, neoverene, vyrazene, path=None, poznamka=""):
    path = path or SOUBOR.with_name("nabidky.html")
    karty = []
    for v in sorted(vysledky, key=lambda x: x.get("skore", 0), reverse=True) + neoverene:
        overeno = "skore" in v
        score = str(v["skore"]) + "/100" if overeno else "Bez hodnocení"
        typ = v.get("kategorie", "Nezařazeno")
        url = v.get("odkaz", "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ("www.jobs.cz", "jobs.cz", "prace.cz", "www.prace.cz", "startupjobs.cz", "www.startupjobs.cz"):
            url = URL
        duvody = "".join("<li>" + escape(str(d)) + "</li>" for d in v.get("duvody", []))
        if not overeno:
            duvody = "<li>Popis se nepodařilo načíst. Požadavky ověř přímo v nabídce.</li>"
        nove = '<span class="new">Nová nabídka</span>' if v.get("novy") else ""
        karty.append(f'''<article data-type="{escape(typ, quote=True)}" data-new="{int(bool(v.get('novy')))}" data-score="{v.get('skore', -1)}">
        <div class="meta">{escape(typ)} · {escape(v.get("portal", "Jobs.cz"))} {nove}</div><h2><a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{escape(v.get('nazev', 'Nabídka'))}</a></h2>
        <div class="score">{escape(score)} <small>{'bodů shody' if overeno else ''}</small></div><ul>{duvody}</ul>
        <a class="open" href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">Otevřít původní inzerát ↗</a></article>''')
    excluded = "".join("<li>" + escape(t) + "</li>" for t in sorted(vyrazene))
    page = '''<!doctype html><html lang="cs"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Moje pracovní nabídky</title><style>
    *{box-sizing:border-box}body{margin:0;background:#f3f6fa;color:#17283c;font:16px/1.6 system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:36px 22px}
    h1{font-size:36px;line-height:1.2;margin:8px 0}header p{color:#506278;max-width:800px}.eyebrow{color:#006e69;font-weight:700;letter-spacing:.1em;font-size:13px}
    .filters{display:flex;flex-wrap:wrap;gap:16px;padding:20px;background:white;border-radius:16px;margin:24px 0}label{display:flex;gap:8px;align-items:center;flex-wrap:wrap}input,select{font:inherit;padding:8px;border:1px solid #acbaca;border-radius:6px}input[type=search]{max-width:100%;width:220px}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:20px}article{background:white;border:1px solid #dde5ed;border-radius:16px;padding:25px}article[hidden]{display:none}h2{font-size:21px;line-height:1.35;margin:12px 0}a{color:#125b83;text-decoration:none}a:hover{text-decoration:underline}.meta{font-size:13px;color:#536779}.new{background:#d8f4e9;color:#14604b;border-radius:20px;padding:4px 9px;margin-left:8px}.score{font-size:25px;font-weight:700}.score small{font-size:13px;font-weight:400;color:#536779}ul{padding-left:20px;font-size:14px}.open{font-weight:650}details{margin-top:25px}footer{margin-top:30px;color:#536779;font-size:13px}.notice{padding:12px;background:#fff2d4;border-radius:8px}#empty{padding:25px;background:white;border-radius:12px}
    </style><main><header><div class="eyebrow">OSOBNÍ PRACOVNÍ PŘEHLED</div><h1>Další krok v kariéře</h1>
    <p>QA tester, datový analytik a Prompt Engineer. Nabídky jsou seřazené podle orientační shody s aktuálními preferencemi. Body nevyjadřují šanci na přijetí.</p></header>'''
    if poznamka:
        page += '<p class="notice">' + escape(poznamka) + '</p>'
    page += f'<p>Vytvořeno {datetime.now().strftime("%d. %m. %Y %H:%M")} · Hodnocených: {len(vysledky)} · Bez hodnocení: {len(neoverene)} · Nových: {sum(bool(v.get("novy")) for v in vysledky)}</p>'
    page += '''<div class="filters"><label>Pozice <select id="type"><option value="">Všechny</option><option>QA tester</option><option>Datový analytik</option><option>Prompt Engineer</option></select></label>
    <label>Hledat <input id="search" type="search" placeholder="Název nebo požadavek"></label><label><input id="new" type="checkbox"> Jen nové</label>
    <label>Skóre <select id="score"><option value="-1">Včetně nehodnocených</option><option value="0">Jen hodnocené</option><option value="50">50 a více</option><option value="70">70 a více</option></select></label></div>
    <p id="count" aria-live="polite"></p><div class="grid">'''
    page += "".join(karty) + '</div><p id="empty" hidden>Pro tento výběr nejsou žádné nabídky. Zkus změnit filtry. Prázdný výsledek neznamená, že na webu žádná nabídka není.</p>'
    if excluded:
        page += '<details><summary>Prompt pozice vyřazené filtrem úrovně nebo názvu</summary><ul>' + excluded + '</ul></details>'
    page += f'<footer>Nejvýše {MAX_STRAN} stránky na dotaz. Nedostupné stránky mohou způsobit neúplné výsledky. Nová = dosud nebyla v JSON paměti; nejde o datum zveřejnění. Dostupnost a podmínky ověř na původním portálu.</footer></main>'
    page += '''<script>
    const cards=[...document.querySelectorAll('article')];const el=id=>document.getElementById(id);
    const norm=t=>t.toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g,'');
    function filter(){let n=0;for(const c of cards){const show=(!el('type').value||c.dataset.type===el('type').value)&&(!el('new').checked||c.dataset.new==='1')&&(Number(c.dataset.score)>=Number(el('score').value))&&norm(c.textContent).includes(norm(el('search').value));c.hidden=!show;if(show)n++;}el('count').textContent='Zobrazeno '+n+' z '+cards.length;el('empty').hidden=n!==0;}
    for(const id of ['type','new','score','search'])el(id).addEventListener('input',filter);filter();</script></html>'''
    path.write_text(page, encoding="utf-8")
    return path


def main():
    try:
        pamet = nacti_pamet(SOUBOR)
    except (OSError, ValueError) as e:
        print(f"Paměť nelze bezpečně načíst: {e}")
        return
    print("PRACOVNÍ AGENT – QA / DATA / PROMPTY")
    print("Skóre 0–100 je orientační shoda s preferencemi, nikoli šance na přijetí.")
    nove, vysledky, nalezene = 0, [], {}
    vyrazene_prompt = set()
    neoverene = []
    with requests.Session() as session:
        session.headers.update({"User-Agent": "Mozilla/5.0", "Accept-Language": "cs,en;q=0.8"})
        for dotaz in HLEDANI:
            print("\nHledám:", dotaz)
            predchozi = set()
            for strana in range(1, MAX_STRAN + 1):
                soup = stahni(session, URL, {"q[]": dotaz, "page": strana})
                if soup is None:
                    break
                polozky = odkazy(soup)
                for a in soup.find_all("a", href=True):
                    title = a.get_text(" ", strip=True)
                    if "/rpd/" in a["href"] and "prompt" in normal(title) and not kategorie(title):
                        vyrazene_prompt.add(title)
                nalezene.update(polozky)
                ids = {a["href"].split("?")[0] for a in soup.find_all("a", href=True) if "/rpd/" in a["href"]}
                if not ids:
                    print("Žádné odkazy na nabídky: prázdný výsledek nebo změna/blokování stránky.")
                    break
                if ids <= predchozi:
                    break
                predchozi.update(ids)
                if not soup.find("a", href=True, attrs={"rel": "next"}) and not any(
                    re.search(r"dalsi|next", normal(a.get_text(" ", strip=True) + " " + str(a.get("aria-label", ""))))
                    for a in soup.find_all("a", href=True)):
                    break
        nalezene.update(prohledej_portaly(session))
        print("\nVyhodnocuji nalezené nabídky...")
        for ident, nabidka in nalezene.items():
            stary = pamet.get(ident, {})
            if cerstvy(stary):
                zaznam = dict(stary)
            else:
                soup = stahni(session, nabidka["odkaz"])
                text = detail(soup) if soup is not None else None
                if not text and soup is not None:
                    text = firemni_detail(session, soup, ident) if nabidka.get("portal", "Jobs.cz") == "Jobs.cz" else None
                if not text and soup is not None and nabidka.get("portal"):
                    # Obecný bezpečný fallback jen pro detail konkrétní nabídky.
                    node = soup.select_one("main article, main [class*=description], main")
                    if node:
                        text = node.get_text(" ", strip=True)[:12000] or None
                if not text:
                    print("Detail neověřen, zkusím příště:", nabidka["odkaz"])
                    neoverene.append(nabidka)
                    continue
                skore, duvody = ohodnot(nabidka["nazev"], text, nabidka["kategorie"])
                zaznam = {**stary, **nabidka, "skore": skore, "duvody": duvody,
                          "vyhodnoceno": True, "verze_hodnoceni": VERZE,
                          "zkontrolovano": datetime.now(timezone.utc).isoformat()}
            zaznam["novy"] = ident not in pamet
            nove += int(zaznam["novy"])
            pamet[ident] = zaznam
            vysledky.append(zaznam)
        if vysledky:
            uloz_pamet(SOUBOR, pamet)
    for typ in ("QA tester", "Datový analytik", "Prompt Engineer"):
        print("\n" + "=" * 55 + "\n" + typ)
        skupina = sorted((v for v in vysledky if v.get("kategorie") == typ), key=lambda v: v["skore"], reverse=True)
        if not skupina:
            print("V tomto běhu žádná ověřená nabídka. Neznamená to, že na webu žádná není.")
        if typ == "Prompt Engineer" and vyrazene_prompt:
            print("Vyřazeno filtrem úrovně nebo názvu: " + "; ".join(sorted(vyrazene_prompt)))
        for v in skupina:
            print(f"\n{v['nazev']} — {v['skore']}/100 bodů" + (" [NOVÝ]" if v["novy"] else ""))
            for d in v["duvody"]:
                print(" -", d)
            print(v["odkaz"])
    if neoverene:
        print("\nNABÍDKY BEZ HODNOCENÍ – popis se nepodařilo načíst:")
        for v in neoverene:
            print(f"{v['nazev']} ({v['kategorie']})\n{v['odkaz']}")
    print(f"\nOvěřeno: {len(vysledky)}, bez hodnocení: {len(neoverene)}, nových: {nove}, celkem v paměti: {len(pamet)}")
    print(f"Hledání omezeno na nejvýše {MAX_STRAN} stránky pro každý dotaz.")
    report = vytvor_report(vysledky, neoverene, vyrazene_prompt)
    print(f"\nPřehled v prohlížeči: {report.resolve()}")
    print("Otevři soubor nabidky.html dvojklikem.")
    if nove > 0:
        from upozorneni import posli_email
        posli_email(vysledky)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nPřerušeno. Poslední uložená paměť zůstává zachována.")
    except OSError as e:
        print(f"Chyba souboru: {e}. Zkontroluj oprávnění a zálohu inzeraty.json.bak.")

