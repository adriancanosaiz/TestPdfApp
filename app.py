from flask import Flask, render_template, request, redirect, url_for, flash, session
import PyPDF2
import requests
import json
from datetime import datetime
import os
import time
import requests
import json
from dotenv import load_dotenv
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, DateField, SelectField
from wtforms.validators import DataRequired, Email, Length, Optional
from urllib.parse import urlparse
import requests
import os
import json


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

    # Campo para el nombre completo
    nombre_completo = StringField('Nombre completo', validators=[DataRequired(), Length(min=3, max=150)])

    # Campo para el correo electrónico
    email = StringField('Correo electrónico', validators=[DataRequired(), Email()])

    # Campo para la contraseña
    password = PasswordField('Contraseña', validators=[DataRequired(), Length(min=8, message="La contraseña debe tener al menos 8 caracteres")])

    # Campo para el centro de estudios
    centro = StringField('Centro de estudios', validators=[DataRequired()])

    # Campo para la fecha de nacimiento
    fecha_nacimiento = DateField('Fecha de nacimiento', format='%Y-%m-%d', validators=[DataRequired()])

    # Campo para el teléfono (opcional)
    telefono = StringField('Teléfono', validators=[Optional(), Length(max=20)])

    # Campo para el género (opciones desplegables)
    genero = SelectField('Género', choices=[('Masculino', 'Masculino'), ('Femenino', 'Femenino'), ('Otro', 'Otro'), ('Prefiero no decirlo', 'Prefiero no decirlo')], default='Prefiero no decirlo')

    # Campo para el país (esto es solo un ejemplo; puedes añadir una lista de países más completa)
    pais = StringField('País', validators=[DataRequired(), Length(max=100)])

    # Campo para el Estado / Provincia

    estado = StringField('Estado', validators=[DataRequired()])

    # Campo para la ciudad
    ciudad = StringField('Ciudad', validators=[DataRequired(), Length(max=100)])

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
    
def generar_preguntas(texto, cantidad=10, dificultad="medio"):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("La clave de API de Gemini no se ha cargado correctamente.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={api_key}"

    prompt = f"""Crea {cantidad} preguntas tipo test basadas en el siguiente texto:
{texto}

Nivel de dificultad: {dificultad}

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

    intentos = 0
    max_intentos = 3  # Puedes ajustar el número de intentos antes de abandonar

    while intentos < max_intentos:
        try:
            response = requests.post(url, headers=headers, data=json.dumps(data))
            response.raise_for_status()

            # Si la solicitud fue exitosa, procesamos la respuesta
            content = response.json()
            texto_generado = content['candidates'][0]['content']['parts'][0]['text']
            
            if texto_generado.startswith("```"):
                texto_generado = texto_generado.strip().lstrip("```json").lstrip("```").rstrip("```").strip()

            preguntas = json.loads(texto_generado)

            with open('test.json', 'w', encoding='utf-8') as f:
                json.dump(preguntas, f, indent=4, ensure_ascii=False)

            return preguntas

        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:
                # Si es un error 429, esperamos antes de intentar nuevamente
                print("Demasiadas solicitudes. Esperando antes de reintentar...")
                time.sleep(60)  # Espera de 60 segundos antes de reintentar
                intentos += 1
            else:
                print(f"Error al generar las preguntas: {e}")
                return []

        except Exception as e:
            print(f"Error al generar las preguntas: {e}")
            return []

    print("Se ha superado el número máximo de intentos debido a errores de API.")
    return []
    
def obtener_historial_tests(user_id):
    # Consultar los resultados de los tests realizados por el usuario
    cur = mysql.connection.cursor()
    cur.execute('SELECT * FROM test_results WHERE user_id = %s', (user_id,))
    historial_tests = cur.fetchall()
    cur.close()
    return historial_tests

def obtener_historial_pdfs(user_id):
    # Consultar los PDFs subidos por el usuario
    cur = mysql.connection.cursor()
    cur.execute('SELECT * FROM pdf_uploads WHERE user_id = %s', (user_id,))
    historial_pdfs = cur.fetchall()
    cur.close()
    return historial_pdfs

# Rutas
@app.route("/register", methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        nombre_completo = form.nombre_completo.data
        email = form.email.data
        password = form.password.data
        centro = form.centro.data
        fecha_nacimiento = form.fecha_nacimiento.data
        telefono = form.telefono.data or None
        genero = form.genero.data

        # IDs enviados desde el formulario
        pais_id = form.pais.data
        estado_id = form.estado.data
        ciudad = form.ciudad.data  # ya viene como nombre

        # Obtener nombre del país desde JSON
        with open('static/data/countries.json', encoding='utf-8') as f:
            paises = json.load(f)
        nombre_pais = next((p['name'] for p in paises if str(p['id']) == pais_id), '')

        # Obtener nombre del estado desde JSON
        with open('static/data/states.json', encoding='utf-8') as f:
            estados = json.load(f)
        nombre_estado = next((e['name'] for e in estados if str(e['id']) == estado_id), '')

        # Validar si el correo ya existe
        cur = mysql.connection.cursor()
        cur.execute('SELECT id FROM users WHERE email = %s', (email,))
        if cur.fetchone():
            flash('Este correo ya está en uso.', 'danger')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')

        # Insertar nuevo usuario con NOMBRES (no IDs)
        cur.execute('''
            INSERT INTO users (
                nombre_completo, email, password, centro, fecha_nacimiento,
                telefono, genero, pais, estado, ciudad
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            nombre_completo, email, hashed_password, centro, fecha_nacimiento,
            telefono, genero, nombre_pais, nombre_estado, ciudad
        ))

        mysql.connection.commit()
        cur.close()

        flash('Usuario registrado exitosamente!', 'success')
        return redirect(url_for('login'))

    return render_template('register.html', form=form)

import json
from flask import jsonify, request

@app.route('/api/estados')
def obtener_estados():
    pais_id = request.args.get('pais_id')
    if not pais_id:
        return jsonify([])

    try:
        with open('static/data/states.json', encoding='utf-8') as f:
            estados = json.load(f)
        filtrados = [ {'id': e['id'], 'name': e['name']} for e in estados if str(e['country_id']) == pais_id ]
        return jsonify(sorted(filtrados, key=lambda x: x['name']))
    except Exception as e:
        print("Error al leer states.json:", e)
        return jsonify([])

@app.route('/api/ciudades')
def obtener_ciudades():
    estado_id = request.args.get('estado_id')
    if not estado_id:
        return jsonify([])

    try:
        with open('static/data/cities.json', encoding='utf-8') as f:
            ciudades = json.load(f)
        filtradas = [ c['name'] for c in ciudades if str(c['state_id']) == estado_id ]
        return jsonify(sorted(filtradas))
    except Exception as e:
        print("Error al leer cities.json:", e)
        return jsonify([])

@app.route("/login", methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data
        password = form.password.data

        # Verificar usuario en la base de datos
        cur = mysql.connection.cursor()
        cur.execute('SELECT id, nombre_completo, email, password FROM users WHERE email = %s', (email,))
        user = cur.fetchone()
        cur.close()

        # Validar credenciales
        if user and check_password_hash(user[3], password):  # user[3] es la contraseña hasheada
            flash('¡Inicio de sesión exitoso!', 'success')
            session['logged_in'] = True
            session['username'] = user[1]  # nombre_completo
            session['email'] = user[2]     # email
            session['user_id'] = user[0]   # id
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

            # Obtener valores del formulario
            cantidad = int(request.form.get("cantidad", 10))
            dificultad = request.form.get("dificultad", "medio")

            # Generar preguntas
            preguntas = generar_preguntas(texto, cantidad=cantidad, dificultad=dificultad)

            return render_template('test.html', preguntas=preguntas)

    return render_template('index.html')

@app.route("/profile", methods=["GET", "POST"])
def profile():
    if not session.get('logged_in'):
        return redirect(url_for('home'))

    user_id = session['user_id']
    cur = mysql.connection.cursor()

    # Obtener los datos actuales del usuario por ID
    cur.execute('SELECT * FROM users WHERE id = %s', (user_id,))
    user = cur.fetchone()

    if request.method == "POST":
        nombre_completo = request.form['nombre_completo']
        genero = request.form['genero']
        telefono = request.form['telefono']
        fecha_nacimiento = request.form['fecha_nacimiento'] if request.form['fecha_nacimiento'] else None
        centro = request.form['centro']
        email = request.form['email']
        nueva_password = request.form['password']

        # Verificar si el nuevo email ya está en uso por otro usuario
        cur.execute('SELECT * FROM users WHERE email = %s AND id != %s', (email, user_id))
        existing_user = cur.fetchone()

        if existing_user:
            flash("El correo electrónico ya está en uso por otro usuario.", "danger")
        else:
            # Si el campo de contraseña no está vacío, la actualiza
            if nueva_password.strip():
                hashed_password = generate_password_hash(nueva_password)
                cur.execute('''
                    UPDATE users 
                    SET nombre_completo = %s, genero = %s, telefono = %s, fecha_nacimiento = %s,
                        centro = %s, email = %s, password = %s
                    WHERE id = %s
                ''', (nombre_completo, genero, telefono, fecha_nacimiento, centro, email, hashed_password, user_id))
            else:
                cur.execute('''
                    UPDATE users 
                    SET nombre_completo = %s, genero = %s, telefono = %s, fecha_nacimiento = %s,
                        centro = %s, email = %s
                    WHERE id = %s
                ''', (nombre_completo, genero, telefono, fecha_nacimiento, centro, email, user_id))

            mysql.connection.commit()

            session['username'] = nombre_completo
            flash("Perfil actualizado correctamente.", "success")
            return redirect(url_for('profile'))

    # Refrescar datos después de posible actualización
    cur.execute('SELECT * FROM users WHERE id = %s', (user_id,))
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

from flask import Flask, render_template

@app.route('/ver_pdfs_subidos')
def ver_pdfs_subidos():
    user_id = session.get('user_id')  # Usamos el user_id almacenado en la sesión
    if not user_id:
        flash('Debes iniciar sesión para ver tus PDFs subidos.', 'danger')
        return redirect(url_for('login'))

    # Recuperar historial de PDFs subidos
    historial_pdfs = obtener_historial_pdfs(user_id)
    return render_template('ver_pdfs_subidos.html', historial_pdfs=historial_pdfs)

@app.route('/ver_tests_realizados')
def ver_tests_realizados():
    # Asegúrate de que el usuario esté autenticado
    user_id = session.get('user_id')  # O usa current_user.id si usas Flask-Login
    
    if not user_id:
        return redirect(url_for('login'))  # Si no está autenticado, redirigir al login

    # Obtener el historial de tests
    historial_tests = obtener_historial_tests(user_id)  # Llamada a la función que obtendrá los tests realizados

    return render_template('ver_tests_realizados.html', historial_tests=historial_tests)

if __name__ == "__main__":
    app.run(debug=True)