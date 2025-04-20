# Importación de módulos necesarios
import tkinter as tk  # Interfaz gráfica
from tkinter import filedialog, messagebox  # Para abrir archivos y mostrar alertas
import fitz  # Librería PyMuPDF para leer PDFs
import json  # Para manejar respuestas JSON
import google.generativeai as genai  # Librería de Gemini
import os
import random
import hashlib

# Configuración de la API de Gemini
# ⚠️ Reemplaza esta clave por tu clave propia desde Google AI Studio
os.environ["GOOGLE_API_KEY"] = "TU_API_KEY_AQUI"
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

# Selección del modelo de Gemini
model_name = "models/gemini-1.5-flash-latest"
model = genai.GenerativeModel(model_name)

# Clase principal de la aplicación
class TestApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Generador de Test desde PDF con Gemini")
        self.root.geometry("700x600")

        # Entrada para el número de preguntas
        self.num_label = tk.Label(root, text="Número de preguntas:")
        self.num_label.pack()
        self.num_entry = tk.Entry(root)
        self.num_entry.insert(0, "10")
        self.num_entry.pack(pady=5)

        # Botón para subir el PDF
        self.upload_button = tk.Button(root, text="Subir PDF", command=self.upload_pdf)
        self.upload_button.pack(pady=10)

        self.text_label = tk.Label(root, text="")
        self.text_label.pack()

        self.question_frame = tk.Frame(root)
        self.question_frame.pack(pady=20)

        # Inicialización de variables de control
        self.current_question = 0
        self.score = 0
        self.questions = []
        self.resumen = []

    def upload_pdf(self):
        try:
            num_preguntas = int(self.num_entry.get())
            if num_preguntas < 1:
                raise ValueError("El número debe ser positivo.")
        except:
            messagebox.showerror("Error", "Introduce un número válido de preguntas.")
            return

        file_path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if file_path:
            self.text_label.config(text="Extrayendo texto del PDF...")
            self.root.update()
            pdf_text = self.extract_text_from_pdf(file_path)

            self.text_label.config(text="Generando preguntas con Gemini...")
            self.root.update()
            self.questions = self.generate_questions_from_text(pdf_text, num_preguntas)

            if self.questions:
                self.current_question = 0
                self.score = 0
                self.resumen = []
                self.show_question()
            else:
                messagebox.showerror("Error", "No se generaron preguntas.")

    def extract_text_from_pdf(self, file_path):
        # Extrae texto de todo el PDF
        text = ""
        with fitz.open(file_path) as doc:
            for page in doc:
                text += page.get_text()
        return text

    def dividir_en_bloques(self, texto, max_chars=3000):
        # Divide el texto en bloques de tamaño máximo
        return [texto[i:i + max_chars] for i in range(0, len(texto), max_chars)]

    def generate_questions_from_text(self, text, total_preguntas):
        bloques = self.dividir_en_bloques(text)

        # Generar una semilla diferente cada vez (aunque sea el mismo contenido)
        random.seed(hashlib.sha256((text + str(random.random())).encode('utf-8')).hexdigest())

        preguntas_por_bloque = max(1, total_preguntas // len(bloques))
        questions = []

        frases_random = [
            "Por favor, crea un test educativo.",
            "Imagina que estás generando un examen.",
            "Diseña preguntas para un cuestionario de repaso.",
            "Genera preguntas únicas para evaluar el contenido.",
            "Haz un test interesante y desafiante."
        ]

        estilos = [
            "Hazlo con estilo formal.",
            "Incluye preguntas variadas.",
            "Evita preguntas repetitivas.",
            "No uses siempre la misma estructura.",
            "Sé creativo en el enfoque."
        ]

        for i, chunk in enumerate(bloques):
            cantidad = min(preguntas_por_bloque, total_preguntas - len(questions))
            if cantidad <= 0:
                break

            frase_random = random.choice(frases_random)
            estilo = random.choice(estilos)

            prompt = f"""
{frase_random} {estilo} a partir del siguiente texto. 
Cada pregunta debe tener solo una respuesta correcta y 3 incorrectas.

Devuelve solo una lista JSON con este formato exacto:
[
  {{
    "pregunta": "...",
    "opciones": ["...", "...", "...", "..."],
    "correcta": "..."
  }}
]

No escribas ningún comentario, encabezado o explicación antes o después del JSON.

Texto:
{chunk}
"""

            try:
                response = model.generate_content(prompt)
                generated_text = response.text.strip()
                cleaned_text = self.clean_response(generated_text)

                if cleaned_text.startswith("[") and cleaned_text.endswith("]"):
                    try:
                        bloque_questions = json.loads(cleaned_text)
                        random.shuffle(bloque_questions)
                        questions.extend(bloque_questions[:cantidad])
                    except json.JSONDecodeError:
                        messagebox.showerror("Error", f"El bloque {i+1} no devolvió un JSON válido.")
                        continue
                else:
                    messagebox.showerror("Error", f"El bloque {i+1} no devolvió un JSON válido.")
                    continue
            except Exception as e:
                print(f"Error en el bloque {i+1}:", e)
                continue

        random.shuffle(questions)
        return questions

    def clean_response(self, text):
        # Elimina basura antes o después del JSON
        try:
            start = text.find('[')
            end = text.rfind(']') + 1
            return text[start:end]
        except:
            return text

    def show_question(self):
        for widget in self.question_frame.winfo_children():
            widget.destroy()

        if self.current_question < len(self.questions):
            q = self.questions[self.current_question]
            question_label = tk.Label(self.question_frame, text=q['pregunta'], wraplength=600, justify="left", font=("Arial", 12, "bold"))
            question_label.pack()

            for opcion in q['opciones']:
                b = tk.Button(self.question_frame, text=opcion, command=lambda opt=opcion: self.check_answer(opt))
                b.pack(fill="x", padx=50, pady=3)
        else:
            self.show_result()

    def check_answer(self, selected):
        q = self.questions[self.current_question]
        correcta = q['correcta']
        fue_correcta = selected == correcta
        if fue_correcta:
            self.score += 1
            messagebox.showinfo("Respuesta", "✅ ¡Correcto!")
        else:
            messagebox.showinfo("Respuesta", f"❌ Incorrecto. La correcta era: {correcta}")

        self.resumen.append({
            "pregunta": q['pregunta'],
            "respuesta_usuario": selected,
            "respuesta_correcta": correcta,
            "es_correcta": fue_correcta
        })

        self.current_question += 1
        self.show_question()

    def show_result(self):
        total = len(self.questions)
        nota = int((self.score / total) * 100)
        resumen_text = f"Tu nota final es: {nota}/100\nRespuestas correctas: {self.score} de {total}\n\nResumen:\n\n"

        for i, r in enumerate(self.resumen):
            resumen_text += f"{i+1}. {r['pregunta']}\n"
            resumen_text += f"   Tu respuesta: {r['respuesta_usuario']}\n"
            resumen_text += f"   Respuesta correcta: {r['respuesta_correcta']}\n"
            resumen_text += f"   {'✅ Correcta' if r['es_correcta'] else '❌ Incorrecta'}\n\n"

        self.mostrar_resumen_en_ventana(resumen_text)

    def mostrar_resumen_en_ventana(self, resumen):
        ventana = tk.Toplevel(self.root)
        ventana.title("Resumen del Test")
        ventana.geometry("700x600")

        text_widget = tk.Text(ventana, wrap="word")
        text_widget.insert("1.0", resumen)
        text_widget.config(state="disabled")
        text_widget.pack(expand=True, fill="both")

        cerrar = tk.Button(ventana, text="Cerrar", command=ventana.destroy)
        cerrar.pack(pady=10)

# Inicia la aplicación
if __name__ == "__main__":
    root = tk.Tk()
    app = TestApp(root)
    root.mainloop()