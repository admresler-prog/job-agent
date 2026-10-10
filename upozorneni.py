"""Volitelné e-mailové upozornění přes Gmail SMTP (heslo jen v GitHub Secrets)."""
import os
import smtplib
from email.message import EmailMessage

WEB = 'https://admresler-prog.github.io/job-agent/nabidky.html'

def posli_email(vysledky):
    nove = [v for v in vysledky if v.get('novy') and v.get('skore', 0) >= 60]
    if not nove:
        return
    odesilatel = os.getenv('GMAIL_ADDRESS', '')
    heslo = os.getenv('GMAIL_APP_PASSWORD', '')
    prijemce = os.getenv('NOTIFY_EMAIL', '')
    if not (odesilatel and heslo and prijemce):
        print('E-mail nenastaven: přidej GitHub Secrets GMAIL_ADDRESS, GMAIL_APP_PASSWORD a NOTIFY_EMAIL.')
        return
    zprava = EmailMessage()
    zprava['Subject'] = f'Pracovní agent: {len(nove)} nových vhodných nabídek'
    zprava['From'] = odesilatel
    zprava['To'] = prijemce
    polozky = '\n\n'.join(f"{v['nazev']} — {v['skore']}/100\n{v['odkaz']}" for v in sorted(nove, key=lambda x: -x['skore']))
    zprava.set_content(f'Nové nabídky se skóre alespoň 60/100:\n\n{polozky}\n\nPřehled: {WEB}')
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30) as smtp:
        smtp.login(odesilatel, heslo)
        smtp.send_message(zprava)
    print(f'E-mail odeslán: {len(nove)} nabídek.')
