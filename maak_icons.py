from PIL import Image

GROEN = (41, 129, 95)  # #29815f
SRC   = "Padel racket.png"

racket = Image.open(SRC).convert("RGBA")
r_w, r_h = racket.size

def maak_icon(maat, bestand):
    canvas = Image.new("RGBA", (maat, maat), GROEN + (255,))
    doel_w = int(maat * 0.80)
    doel_h = int(doel_w * r_h / r_w)
    if doel_h > int(maat * 0.80):
        doel_h = int(maat * 0.80)
        doel_w = int(doel_h * r_w / r_h)
    geschaald = racket.resize((doel_w, doel_h), Image.LANCZOS)
    x = (maat - doel_w) // 2
    y = (maat - doel_h) // 2
    canvas.paste(geschaald, (x, y), geschaald)
    canvas.convert("RGB").save(bestand, "PNG", optimize=True)
    print(f"{bestand}: {doel_w}x{doel_h} in {maat}x{maat}")

maak_icon(192, "icon-192.png")
maak_icon(512, "icon-512.png")
maak_icon(180, "apple-touch-icon.png")
