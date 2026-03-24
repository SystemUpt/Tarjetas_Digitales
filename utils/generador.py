import os
from PIL import Image, ImageDraw, ImageFont
import barcode
from barcode.writer import ImageWriter

def crear_tarjeta(nombre, telefono):
    base_dir = os.path.dirname(os.path.dirname(__file__))
    plantilla_path = os.path.join(base_dir, "static", "plantilla.png")
    barcode_dir = os.path.join(base_dir, "static", "barcodes")
    output_dir = os.path.join(base_dir, "static", "output")

    os.makedirs(barcode_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    # Generar código de barras
    codigo_path = os.path.join(barcode_dir, telefono)
    code128 = barcode.get("code128", telefono, writer=ImageWriter())
    barcode_file = code128.save(codigo_path)

    # Abrir plantilla
    tarjeta = Image.open(plantilla_path).convert("RGB")
    draw = ImageDraw.Draw(tarjeta)

    # Fuentes
    try:
        font_nombre = ImageFont.truetype("arial.ttf", 40)
    except:
        font_nombre = ImageFont.load_default()

    # Escribir nombre
    draw.text((80, 180), nombre, fill="black", font=font_nombre)

    # Pegar código de barras
    barcode_img = Image.open(barcode_file).convert("RGB")
    barcode_img = barcode_img.resize((350, 120))
    tarjeta.paste(barcode_img, (210, 250))

    # Guardar resultado
    nombre_archivo = f"{telefono}.png"
    salida = os.path.join(output_dir, nombre_archivo)
    tarjeta.save(salida)

    return salida