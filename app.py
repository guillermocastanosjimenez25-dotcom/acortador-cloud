import os
import re
import secrets
import string
from urllib.parse import urlsplit

from dotenv import load_dotenv
from flask import Flask, request, render_template_string, redirect, abort
from postgrest.exceptions import APIError
from supabase import create_client


load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

BASE_URL = os.environ["APP_BASE_URL"].rstrip("/")

db = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SECRET_KEY"]
)

ALPHABET = string.ascii_letters + string.digits


HTML = """
<!doctype html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">

    <title>Acortador Cloud</title>

    <style>
        body {
            font-family: Arial, sans-serif;
            background: #eef3f8;
            margin: 0;
            padding: 30px;
            color: #142538;
        }

        main {
            max-width: 650px;
            margin: 50px auto;
            background: white;
            padding: 30px;
            border-radius: 14px;
            box-shadow: 0 8px 30px #0001;
        }

        input {
            box-sizing: border-box;
            width: 100%;
            padding: 12px;
            margin: 12px 0;
            border: 1px solid #bbc7d4;
            border-radius: 6px;
            font-size: 16px;
        }

        button {
            background: #174b78;
            color: white;
            padding: 12px 20px;
            border: 0;
            border-radius: 6px;
            cursor: pointer;
            font-size: 16px;
        }

        a {
            color: #174b78;
            overflow-wrap: anywhere;
        }

        .error {
            color: #a32020;
        }
    </style>
</head>

<body>
    <main>
        <h1>Acortador de enlaces</h1>

        <p>
            Introduce una dirección y genera un enlace
            con un código breve.
        </p>

        <form method="post">
            <label for="url">URL original</label>

            <input
                id="url"
                name="url"
                type="url"
                maxlength="4096"
                placeholder="https://ejemplo.com/ruta/larga"
                required
            >

            <button type="submit">Acortar enlace</button>
        </form>

        {% if short %}
            <p>
                Enlace generado:
                <a href="{{ short }}">{{ short }}</a>
            </p>
        {% endif %}

        {% if error %}
            <p class="error" role="alert">{{ error }}</p>
        {% endif %}
    </main>
</body>
</html>
"""


def valid_url(value):
    """Comprueba que la dirección tenga un formato admitido."""

    if len(value) > 4096:
        return False

    if re.search(r"[\s\x00-\x1f\x7f]", value):
        return False

    try:
        parsed = urlsplit(value)

        # Comprueba también que el puerto sea válido.
        _ = parsed.port

        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
        )

    except ValueError:
        return False


@app.route("/", methods=["GET", "POST"])
def home():
    short = None
    error = None
    status = 200

    if request.method == "POST":
        original = request.form.get("url", "").strip()

        if not valid_url(original):
            error = "Introduce una URL válida con http:// o https://."
            status = 400

        else:
            try:
                # Reintenta si un código ya existe.
                for _ in range(5):
                    code = "".join(
                        secrets.choice(ALPHABET)
                        for _ in range(8)
                    )

                    try:
                        db.table("enlaces").insert({
                            "url_original": original,
                            "url_corta": code
                        }).execute()

                        short = f"{BASE_URL}/{code}"
                        break

                    except APIError as exc:
                        # 23505 significa clave duplicada.
                        if exc.code != "23505":
                            raise

                if short is None:
                    error = (
                        "No se pudo generar el código. "
                        "Inténtalo otra vez."
                    )
                    status = 503

            except Exception:
                app.logger.error(
                    "No se pudo guardar el enlace."
                )

                error = (
                    "Base de datos no disponible. "
                    "Inténtalo más tarde."
                )
                status = 503

    return render_template_string(
        HTML,
        short=short,
        error=error
    ), status


@app.get("/<code>")
def follow(code):
    if not re.fullmatch(r"[A-Za-z0-9]{8}", code):
        abort(404)

    try:
        rows = (
            db.table("enlaces")
            .select("url_original")
            .eq("url_corta", code)
            .limit(1)
            .execute()
            .data
        )

    except Exception:
        abort(503)

    if not rows:
        abort(404)

    destination = rows[0]["url_original"]

    if not valid_url(destination):
        abort(400)

    return redirect(destination, code=302)


@app.get("/health")
def health():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False
    )