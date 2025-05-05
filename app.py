from flask import Flask, render_template, request, redirect, url_for, flash, session
import PyPDF2
import requests
import json
from datetime import datetime
import os
from dotenv import load_dotenv
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, DateField
from wtforms.validators import DataRequired, Email, Length
from urllib.parse import urlparse


# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'mysecretkey'  # Cambia esto en producción


# Cargar la URL de conexión desde las variables de entorno
mysql_url = os.getenv('MYSQL_URL')

# Analizar la URL
url = urlparse(mysql_url)

# Configuración de MySQL usando los valores de la URL
app.config['MYSQL_HOST'] = url.hostname
app.config['MYSQL_USER'] = url.username
app.config['MYSQL_PASSWORD'] = url.password
app.config['MYSQL_DB'] = url.path[1:]  # Eliminar el primer '/' en la ruta
app.config['MYSQL_PORT'] = url.port

# Inicializar MySQL
mysql = MySQL(app)

# Formularios
class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8, message="La contraseña debe tener al menos 8 caracteres")])
    centro = StringField('Centro de estudios', validators=[DataRequired()])
    fecha_nacimiento = DateField('Fecha de nacimiento', format='%Y-%m-%d', validators=[DataRequired()])

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])

# Funciones auxiliares
def extraer_texto_pdf(pdf_file):
    try:
        reader = PyPDF2.PdfReader(pdf_file)
        texto = ""
        for page in reader.pages:
            texto += page.extract_text()
        return texto
    except Exception as e:
        print(f"Error al leer el PDF: {e}")
        return ""

def generar_preguntas(texto):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("La clave de API de Gemini no se ha cargado correctamente.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={api_key}"

    prompt = f"""Crea 10 preguntas tipo test basadas en el siguiente texto:
{texto}

Para cada pregunta, proporciona:
- "pregunta" (el enunciado),
- "opciones" (una lista de 3 o más opciones),
- "respuesta_correcta" (la respuesta correcta),
- "explicacion" (una breve explicación de la respuesta correcta).

La respuesta debe ser estrictamente un JSON válido.
No incluyas comentarios, explicaciones, ni bloques de código como ```json o similares.
Solo responde con el JSON directamente, limpio y listo para parsear.
"""

    data = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        content = response.json()

        texto_generado = content['candidates'][0]['content']['parts'][0]['text']
        print("Respuesta cruda de Gemini:", texto_generado)

        # Limpieza extra si empieza por ```
        if texto_generado.startswith("```"):
            texto_generado = texto_generado.strip().lstrip("```json").lstrip("```").rstrip("```").strip()

        preguntas = json.loads(texto_generado)

        # Guardar preguntas en un archivo
        with open('test.json', 'w', encoding='utf-8') as f:
            json.dump(preguntas, f, indent=4, ensure_ascii=False)
        return preguntas
    except Exception as e:
        print(f"Error al generar las preguntas: {e}")
        return []

# Rutas
@app.route("/register", methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        username = form.username.data
        email = form.email.data
        password = form.password.data
        centro = form.centro.data
        fecha_nacimiento = form.fecha_nacimiento.data

        # Validación de correo duplicado
        cur = mysql.connection.cursor()
        cur.execute('SELECT * FROM users WHERE email = %s', (email,))
        if cur.fetchone():
            flash('Este correo ya está en uso.', 'danger')
            return redirect(url_for('register'))

        # Cifrar la contraseña
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')

        # Insertar usuario en la base de datos
        cur.execute('INSERT INTO users (username, email, password, centro, fecha_nacimiento) VALUES (%s, %s, %s, %s, %s)',
                    (username, email, hashed_password, centro, fecha_nacimiento))
        mysql.connection.commit()
        cur.close()

        flash('Usuario registrado exitosamente!', 'success')
        return redirect(url_for('login'))

    return render_template('register.html', form=form)

@app.route("/login", methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data
        password = form.password.data

        # Verificar usuario en la base de datos
        cur = mysql.connection.cursor()
        cur.execute('SELECT * FROM users WHERE email = %s', (email,))
        user = cur.fetchone()
        cur.close()

        # Validar credenciales
        if user and check_password_hash(user[3], password):  # user[3] es la contraseña cifrada en la base de datos
            flash('¡Inicio de sesión exitoso!', 'success')
            session['logged_in'] = True
            session['username'] = user[1]  # Guardar el nombre en la sesión
            session['email'] = user[2]  # Guardar el email en la sesión
            session['user_id'] = user[0]  # Guardar el user_id en la sesión
            return redirect(url_for('index'))
        else:
            flash('Correo electrónico o contraseña incorrectos', 'danger')

    return render_template('login.html', form=form)

@app.route("/logout")
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('home'))

@app.route("/home", methods=["GET"])
def home():
    if session.get('logged_in'):
        return redirect(url_for('index'))
    return render_template("home.html")

@app.route('/index', methods=['GET', 'POST'])
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        if 'pdf' not in request.files:
            flash('No se ha seleccionado ningún archivo.', 'danger')
            return redirect(request.url)

        pdf_file = request.files['pdf']
        if pdf_file.filename == '':
            flash('Nombre de archivo no válido.', 'danger')
            return redirect(request.url)

        # Verificar si el archivo ya fue subido por el usuario
        user_id = session['user_id']
        nombre_archivo = pdf_file.filename

        # Consultar en la base de datos si ya existe un PDF con el mismo nombre para este usuario
        cur = mysql.connection.cursor()
        cur.execute('SELECT * FROM pdf_uploads WHERE user_id = %s AND nombre_archivo = %s', (user_id, nombre_archivo))
        existing_pdf = cur.fetchone()
        cur.close()

        if existing_pdf:
            flash('Ya has subido este archivo anteriormente.', 'danger')
            return redirect(request.url)

        if pdf_file:
            # Crear carpeta específica para el usuario si no existe
            user_folder = os.path.join('uploads', str(user_id))
            os.makedirs(user_folder, exist_ok=True)

            # Guardar el archivo PDF en la carpeta del usuario
            pdf_path = os.path.join(user_folder, pdf_file.filename)
            pdf_file.save(pdf_path)

            # Extraer texto del PDF
            texto = extraer_texto_pdf(pdf_path)

            # Guardar en la base de datos pdf_uploads
            fecha_subida = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            cur = mysql.connection.cursor()
            cur.execute('INSERT INTO pdf_uploads (user_id, nombre_archivo, contenido_texto, fecha_subida) VALUES (%s, %s, %s, %s)',
                        (user_id, nombre_archivo, texto, fecha_subida))
            mysql.connection.commit()
            cur.close()

            # Generar preguntas a partir del texto extraído
            preguntas = generar_preguntas(texto)
            return render_template('test.html', preguntas=preguntas)

    return render_template('index.html')

# Añadir la ruta del perfil
@app.route("/profile")
def profile():
    if not session.get('logged_in'):
        return redirect(url_for('home'))
    
    username = session['username']
    cur = mysql.connection.cursor()
    cur.execute('SELECT * FROM users WHERE username = %s', (username,))
    user = cur.fetchone()
    cur.close()

    return render_template('profile.html', user=user)

@app.route("/test", methods=["GET"])
def test():
    if not session.get('logged_in'):
        return redirect(url_for('home'))
    preguntas = []
    if os.path.exists('test.json'):
        with open('test.json', 'r', encoding='utf-8') as f:
            preguntas = json.load(f)
    return render_template("test.html", preguntas=preguntas)

@app.route("/test/resultado", methods=["POST"])
def test_resultado():
    if not session.get('logged_in'):
        return redirect(url_for('home'))
    correctas = 0
    total_preguntas = 0
    resultado_respuestas = []

    i = 1
    while True:
        pregunta_texto = request.form.get(f'pregunta_texto_{i}')
        respuesta_correcta = request.form.get(f'respuesta_correcta_{i}')
        seleccionada = request.form.get(f'pregunta_{i}')
        explicacion = request.form.get(f'explicacion_{i}')  # Explicación de la respuesta correcta
        if not pregunta_texto:
            break

        es_correcta = (seleccionada == respuesta_correcta)
        if es_correcta:
            correctas += 1

        resultado_respuestas.append({
            'pregunta': pregunta_texto,
            'correcta': respuesta_correcta,
            'seleccionada': seleccionada,
            'explicacion': explicacion,  # Almacenar la explicación
            'es_correcta': es_correcta
        })

        total_preguntas += 1
        i += 1

    fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    nota = (correctas / total_preguntas) * 100 if total_preguntas else 0
    resultado = {
        'fecha': fecha,
        'total_preguntas': total_preguntas,
        'aciertos': correctas,
        'nota': round(nota, 2)
    }

    # Guardar en la base de datos
    user_id = session.get('user_id')
    if user_id:
        cur = mysql.connection.cursor()
        # Primero guardar el test general
        cur.execute('INSERT INTO test_results (user_id, fecha, total_preguntas, aciertos, nota) VALUES (%s, %s, %s, %s, %s)',
                    (user_id, fecha, total_preguntas, correctas, round(nota, 2)))
        test_result_id = cur.lastrowid  # ID del test recién creado

        # Ahora guardar cada respuesta individual, incluyendo la explicación
        for res in resultado_respuestas:
            cur.execute('INSERT INTO test_answers (test_result_id, pregunta, respuesta_correcta, respuesta_seleccionada, es_correcta, explicacion) VALUES (%s, %s, %s, %s, %s, %s)',
                        (test_result_id, res['pregunta'], res['correcta'], res['seleccionada'], res['es_correcta'], res['explicacion']))
        mysql.connection.commit()
        cur.close()

    return render_template("test_resultado.html", resultado=resultado, respuestas=resultado_respuestas)

@app.route("/test/<int:test_result_id>")
def ver_detalle_test(test_result_id):
    if not session.get('logged_in'):
        return redirect(url_for('home'))

    cur = mysql.connection.cursor()
    # Cargar los datos del test (opcional, si quieres mostrar la nota o fecha)
    cur.execute('SELECT * FROM test_results WHERE id = %s', (test_result_id,))
    test_info = cur.fetchone()

    # Cargar las respuestas del test
    cur.execute('SELECT pregunta, respuesta_correcta, respuesta_seleccionada, es_correcta, explicacion FROM test_answers WHERE test_result_id = %s', (test_result_id,))    
    respuestas = cur.fetchall()

    cur.close()

    return render_template('detalle_test.html', test_info=test_info, respuestas=respuestas)

@app.route("/historial", methods=["GET"])
def historial():
    if not session.get('logged_in'):
        return redirect(url_for('home'))

    user_id = session.get('user_id')  # Usamos .get() para evitar el KeyError
    if not user_id:
        flash("Debes iniciar sesión para ver tu historial.", "danger")
        return redirect(url_for('login'))
    
    # Obtener los resultados de los tests
    cur = mysql.connection.cursor()
    cur.execute('SELECT * FROM test_results WHERE user_id = %s', (user_id,))
    historial_tests = cur.fetchall()
    
    # Obtener los PDFs subidos
    cur.execute('SELECT * FROM pdf_uploads WHERE user_id = %s', (user_id,))
    historial_pdfs = cur.fetchall()
    cur.close()

    return render_template('historial.html', historial_tests=historial_tests, historial_pdfs=historial_pdfs)

@app.route("/generar_test_desde_pdf/<int:pdf_id>", methods=["POST"])
def generar_test_desde_pdf(pdf_id):
    # Verificar que el usuario está autenticado
    if 'user_id' not in session:
        flash('Debes iniciar sesión para generar un test.', 'danger')
        return redirect(url_for('login'))

    # Obtener el contenido del PDF desde la base de datos
    cur = mysql.connection.cursor()
    cur.execute('SELECT contenido_texto FROM pdf_uploads WHERE id = %s', (pdf_id,))
    pdf_data = cur.fetchone()
    cur.close()

    if pdf_data is None:
        flash('El PDF seleccionado no existe o ha sido eliminado.', 'danger')
        return redirect(url_for('historial'))

    texto_pdf = pdf_data[0]

    # Generar las preguntas a partir del texto extraído del PDF
    preguntas = generar_preguntas(texto_pdf)

    if not preguntas:
        flash('No se pudieron generar preguntas para este PDF.', 'danger')
        return redirect(url_for('historial'))

    # Renderizar la página con las preguntas generadas
    return render_template('test.html', preguntas=preguntas)

@app.route('/eliminar_pdf/<int:pdf_id>', methods=['POST'])
def eliminar_pdf(pdf_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    
    # Consultar el archivo PDF para obtener el nombre del archivo y la ruta
    cur = mysql.connection.cursor()
    cur.execute('SELECT * FROM pdf_uploads WHERE user_id = %s AND id = %s', (user_id, pdf_id))
    pdf = cur.fetchone()
    cur.close()

    if not pdf:
        flash('El archivo no existe o no tienes permisos para eliminarlo.', 'danger')
        return redirect(url_for('historial'))

    # Eliminar el archivo físico del sistema
    pdf_path = os.path.join('uploads', str(user_id), pdf[2])
    if os.path.exists(pdf_path):
        os.remove(pdf_path)

    # Eliminar el registro del archivo en la base de datos
    cur = mysql.connection.cursor()
    cur.execute('DELETE FROM pdf_uploads WHERE id = %s', (pdf_id,))
    mysql.connection.commit()
    cur.close()

    flash('El archivo ha sido eliminado exitosamente.', 'success')
    return redirect(url_for('historial'))

if __name__ == "__main__":
    app.run(debug=True)