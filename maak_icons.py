from PIL import Image
import os

GROEN = (41, 129, 95)   # #29815f
SRC   = "Padel racket.png"
MATEN = [192, 512]

racket = Image.open(SRC).convert("RGBA")

for maat in MATEN:
    canvas = Image.new("RGBA", (maat, maat), GROEN + (255,))

    # Racket schalen naar 72% van het icoon, gecentreerd
    schaal  = int(maat * 0.72)
    racket_geschaald = racket.resize((schaal, schaal), Image.LANCZOS)

    # Centreren
    x = (maat - schaal) // 2
    y = (maat - schaal) // 2
    canvas.paste(racket_geschaald, (x, y), racket_geschaald)

    bestand = f"icon-{maat}.png"
    canvas.convert("RGB").save(bestand, "PNG", optimize=True)
    print(f"Aangemaakt: {bestand}")

# Apple touch icon (180x180)
maat   = 180
canvas = Image.new("RGBA", (maat, maat), GROEN + (255,))
schaal = int(maat * 0.72)
racket_geschaald = racket.resize((schaal, schaal), Image.LANCZOS)
x = (maat - schaal) // 2
y = (maat - schaal) // 2
canvas.paste(racket_geschaald, (x, y), racket_geschaald)
canvas.convert("RGB").save("apple-touch-icon.png", "PNG", optimize=True)
print("Aangemaakt: apple-touch-icon.png")
