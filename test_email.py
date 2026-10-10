from upozorneni import posli_email

testovaci_nabidka = {
    "nazev": "TEST – ověření e-mailu pracovního agenta",
    "skore": 100,
    "odkaz": "https://admresler-prog.github.io/job-agent/nabidky.html",
    "novy": True
}

posli_email([testovaci_nabidka])
