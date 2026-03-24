import os
import re
import uuid
import asyncio
import sqlite3

from flask import Flask, render_template, request, redirect, url_for, send_file, abort, flash
import barcode
from barcode.writer import ImageWriter
from playwright.async_api import async_playwright

app = Flask(__name__)
app.secret_key = "superkeno_secret_key"

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
BARCODE_DIR = os.path.join(STATIC_DIR, "barcodes")
PNG_DIR = os.path.join(STATIC_DIR, "tarjetas_png")
DB_PATH = os.path.join(BASE_DIR, "clientes.db")

os.makedirs(BARCODE_DIR, exist_ok=True)
os.makedirs(PNG_DIR, exist_ok=True)


# ----------------------------
# BASE DE DATOS
# ----------------------------
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def existe_otro_cliente_con_telefono(telefono, cliente_id):
    conn = get_db_connection()
    cliente = conn.execute("""
        SELECT id FROM clientes
        WHERE telefono = ? AND id != ?
    """, (telefono, cliente_id)).fetchone()
    conn.close()
    return cliente is not None


def crear_tabla_clientes():
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            telefono TEXT NOT NULL UNIQUE,
            codigo_cliente TEXT NOT NULL,
            barcode_path TEXT,
            png_path TEXT,
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def guardar_o_actualizar_cliente(nombre, telefono, codigo_cliente, barcode_path, png_path=""):
    conn = get_db_connection()

    existente = conn.execute(
        "SELECT id FROM clientes WHERE telefono = ?",
        (telefono,)
    ).fetchone()

    if existente:
        conn.execute("""
            UPDATE clientes
            SET nombre = ?, codigo_cliente = ?, barcode_path = ?, png_path = ?
            WHERE telefono = ?
        """, (nombre, codigo_cliente, barcode_path, png_path, telefono))
    else:
        conn.execute("""
            INSERT INTO clientes (nombre, telefono, codigo_cliente, barcode_path, png_path)
            VALUES (?, ?, ?, ?, ?)
        """, (nombre, telefono, codigo_cliente, barcode_path, png_path))

    conn.commit()
    conn.close()


def actualizar_png_cliente(telefono, png_path):
    conn = get_db_connection()
    conn.execute("""
        UPDATE clientes
        SET png_path = ?
        WHERE telefono = ?
    """, (png_path, telefono))
    conn.commit()
    conn.close()


def buscar_clientes_db(termino):
    conn = get_db_connection()
    resultados = conn.execute("""
        SELECT * FROM clientes
        WHERE nombre LIKE ? OR telefono LIKE ? OR codigo_cliente LIKE ?
        ORDER BY id DESC
    """, (f"%{termino}%", f"%{termino}%", f"%{termino}%")).fetchall()
    conn.close()
    return resultados


def obtener_cliente_por_id(cliente_id):
    conn = get_db_connection()
    cliente = conn.execute(
        "SELECT * FROM clientes WHERE id = ?",
        (cliente_id,)
    ).fetchone()
    conn.close()
    return cliente


# ----------------------------
# UTILIDADES
# ----------------------------
def limpiar_texto(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def limpiar_telefono(telefono: str) -> str:
    return re.sub(r"\D", "", telefono)


def generar_codigo_cliente(telefono: str) -> str:
    ultimos = telefono[-8:] if len(telefono) >= 8 else telefono
    return f"SK{ultimos}"


def generar_codigo_barras(codigo_texto: str) -> str:
    nombre_archivo = f"{codigo_texto}_{uuid.uuid4().hex[:8]}"
    ruta_base = os.path.join(BARCODE_DIR, nombre_archivo)

    writer = ImageWriter()
    writer.set_options({
        "module_width": 1.2,
        "module_height": 60,
        "font_size": 26,
        "text_distance": 5,
        "quiet_zone": 1.2,
        "dpi": 300,
        "write_text": True
    })

    codigo = barcode.get("code128", codigo_texto, writer=writer)
    archivo_generado = codigo.save(ruta_base)

    return os.path.relpath(archivo_generado, BASE_DIR).replace("\\", "/")


async def renderizar_tarjeta_a_png(url_tarjeta: str, ruta_salida_png: str):
    async with async_playwright() as p:

        # 🔍 Detectar ruta de Chromium en Render automáticamente
        playwright_path = "/opt/render/.cache/ms-playwright"

        chromium_dirs = [
            d for d in os.listdir(playwright_path)
            if d.startswith("chromium-")
        ]

        chromium_dirs.sort(reverse=True)

        chromium_path = os.path.join(
            playwright_path,
            chromium_dirs[0],
            "chrome-linux",
            "chrome"
        )

        print("Usando Chromium en:", chromium_path)

        browser = await p.chromium.launch(
            headless=True,
            executable_path=chromium_path,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )

        page = await browser.new_page(
            viewport={"width": 1400, "height": 900},
            device_scale_factor=2
        )

        await page.goto(url_tarjeta, wait_until="domcontentloaded", timeout=60000)

        tarjeta = page.locator(".tarjeta-cliente")

        await tarjeta.screenshot(path=ruta_salida_png)

        await browser.close()


def crear_png_desde_tarjeta(url_tarjeta: str, ruta_salida_png: str):
    try:
        asyncio.run(renderizar_tarjeta_a_png(url_tarjeta, ruta_salida_png))
    except Exception as e:
        print("❌ ERROR AL GENERAR PNG:", str(e))
        raise


# ----------------------------
# RUTAS
# ----------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        nombre = limpiar_texto(request.form.get("nombre", ""))
        telefono = limpiar_telefono(request.form.get("telefono", ""))

        errores = []

        if not nombre:
            errores.append("El nombre es obligatorio.")

        if not telefono:
            errores.append("El teléfono es obligatorio.")

        if telefono and len(telefono) < 10:
            errores.append("El teléfono debe tener al menos 10 dígitos.")

        if errores:
            return render_template(
                "index.html",
                errores=errores,
                nombre=nombre,
                telefono=telefono
            )

        codigo_cliente = generar_codigo_cliente(telefono)
        barcode_path = generar_codigo_barras(codigo_cliente)

        guardar_o_actualizar_cliente(
            nombre=nombre,
            telefono=telefono,
            codigo_cliente=codigo_cliente,
            barcode_path=barcode_path
        )

        return render_template(
            "tarjeta.html",
            nombre=nombre,
            telefono=telefono,
            codigo_cliente=codigo_cliente,
            barcode_path=barcode_path,
            modo_imagen=False
        )

    return render_template("index.html", errores=[], nombre="", telefono="")


@app.route("/tarjeta_img")
def tarjeta_img():
    nombre = limpiar_texto(request.args.get("nombre", ""))
    telefono = limpiar_telefono(request.args.get("telefono", ""))
    codigo_cliente = limpiar_texto(request.args.get("codigo_cliente", ""))
    barcode_path = request.args.get("barcode_path", "")

    if not nombre or not telefono or not codigo_cliente or not barcode_path:
        abort(400, "Faltan parámetros para mostrar la tarjeta.")

    return render_template(
        "tarjeta.html",
        nombre=nombre,
        telefono=telefono,
        codigo_cliente=codigo_cliente,
        barcode_path=barcode_path,
        modo_imagen=True
    )


@app.route("/generar_png", methods=["POST"])
def generar_png():
    nombre = limpiar_texto(request.form.get("nombre", ""))
    telefono = limpiar_telefono(request.form.get("telefono", ""))
    codigo_cliente = limpiar_texto(request.form.get("codigo_cliente", ""))
    barcode_path = request.form.get("barcode_path", "")

    if not nombre or not telefono or not codigo_cliente or not barcode_path:
        abort(400, "Faltan datos para generar el PNG.")

    nombre_png = f"tarjeta_{telefono}_{uuid.uuid4().hex[:6]}.png"
    ruta_png = os.path.join(PNG_DIR, nombre_png)

    url_tarjeta = url_for(
        "tarjeta_img",
        nombre=nombre,
        telefono=telefono,
        codigo_cliente=codigo_cliente,
        barcode_path=barcode_path,
        _external=True
    )

    crear_png_desde_tarjeta(url_tarjeta, ruta_png)

    png_relativo = f"tarjetas_png/{nombre_png}"
    actualizar_png_cliente(telefono, png_relativo)

    return redirect(url_for("resultado_png", archivo=nombre_png, telefono=telefono))


@app.route("/resultado_png")
def resultado_png():
    archivo = request.args.get("archivo", "")
    telefono = limpiar_telefono(request.args.get("telefono", ""))

    if not archivo:
        abort(400, "No se recibió el archivo PNG.")

    ruta_archivo = os.path.join(PNG_DIR, archivo)
    if not os.path.exists(ruta_archivo):
        abort(404, "No se encontró el archivo PNG.")

    ruta_relativa = f"tarjetas_png/{archivo}"
    whatsapp_url = f"https://wa.me/52{telefono}"

    return render_template(
        "resultado_png.html",
        archivo=archivo,
        telefono=telefono,
        ruta_relativa=ruta_relativa,
        whatsapp_url=whatsapp_url
    )


@app.route("/descargar_png/<archivo>")
def descargar_png(archivo):
    ruta_archivo = os.path.join(PNG_DIR, archivo)

    if not os.path.exists(ruta_archivo):
        abort(404, "Archivo no encontrado.")

    return send_file(ruta_archivo, as_attachment=True)


@app.route("/buscar", methods=["GET", "POST"])
def buscar():
    resultados = []
    termino = ""

    if request.method == "POST":
        termino = limpiar_texto(request.form.get("termino", ""))
        if termino:
            resultados = buscar_clientes_db(termino)

    return render_template("buscar.html", resultados=resultados, termino=termino)


@app.route("/ver_cliente/<int:cliente_id>")
def ver_cliente(cliente_id):
    cliente = obtener_cliente_por_id(cliente_id)

    if not cliente:
        abort(404, "Cliente no encontrado.")

    return render_template(
        "tarjeta.html",
        nombre=cliente["nombre"],
        telefono=cliente["telefono"],
        codigo_cliente=cliente["codigo_cliente"],
        barcode_path=cliente["barcode_path"],
        modo_imagen=False
    )

@app.route("/editar_cliente/<int:cliente_id>", methods=["GET", "POST"])
def editar_cliente(cliente_id):
    cliente = obtener_cliente_por_id(cliente_id)

    if not cliente:
        abort(404, "Cliente no encontrado.")

    if request.method == "POST":
        nombre = limpiar_texto(request.form.get("nombre", ""))
        telefono = limpiar_telefono(request.form.get("telefono", ""))

        errores = []

        if not nombre:
            errores.append("El nombre es obligatorio.")

        if not telefono:
            errores.append("El teléfono es obligatorio.")

        if telefono and len(telefono) < 10:
            errores.append("El teléfono debe tener al menos 10 dígitos.")

        if existe_otro_cliente_con_telefono(telefono, cliente_id):
            errores.append("Ya existe otro cliente con ese número de teléfono.")

        if errores:
            return render_template(
                "editar_cliente.html",
                cliente=cliente,
                errores=errores,
                nombre=nombre,
                telefono=telefono
            )

        telefono_anterior = cliente["telefono"]

        # Si cambió el teléfono, regeneramos código e imagen de barras
        if telefono != telefono_anterior:
            codigo_cliente = generar_codigo_cliente(telefono)
            barcode_path = generar_codigo_barras(codigo_cliente)
            png_path = ""  # se limpia para obligar a regenerar PNG
        else:
            codigo_cliente = cliente["codigo_cliente"]
            barcode_path = cliente["barcode_path"]
            png_path = cliente["png_path"] or ""

        conn = get_db_connection()
        conn.execute("""
            UPDATE clientes
            SET nombre = ?, telefono = ?, codigo_cliente = ?, barcode_path = ?, png_path = ?
            WHERE id = ?
        """, (nombre, telefono, codigo_cliente, barcode_path, png_path, cliente_id))
        conn.commit()
        conn.close()

        flash("Cliente actualizado correctamente.")
        return redirect(url_for("ver_cliente", cliente_id=cliente_id))

    return render_template(
        "editar_cliente.html",
        cliente=cliente,
        errores=[],
        nombre=cliente["nombre"],
        telefono=cliente["telefono"]
    )


if __name__ == "__main__":
    crear_tabla_clientes()
    app.run(debug=True)
