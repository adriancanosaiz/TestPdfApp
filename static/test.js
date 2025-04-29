let currentQuestionIndex = 0; // Índice de la pregunta actual
const questions = document.querySelectorAll('.pregunta'); // Seleccionamos todas las preguntas
const totalQuestions = questions.length;

function showQuestion(index) {
    // Ocultar todas las preguntas
    questions.forEach((question, i) => {
        question.style.display = 'none';
    });

    // Mostrar las preguntas actuales según el índice
    questions[index].style.display = 'block';
}

function changeQuestion(direction) {
    currentQuestionIndex += direction;

    // Si el índice está fuera de rango, lo ajustamos
    if (currentQuestionIndex < 0) {
        currentQuestionIndex = 0; // Primera pregunta
    } else if (currentQuestionIndex >= totalQuestions) {
        currentQuestionIndex = totalQuestions - 1; // Última pregunta
    }

    // Mostrar la pregunta actual
    showQuestion(currentQuestionIndex);
}

document.addEventListener('DOMContentLoaded', () => {
    showQuestion(currentQuestionIndex); // Mostrar la primera pregunta al cargar la página

    const respondidasSpan = document.getElementById('respondidas');
    const totalSpan = document.getElementById('total');
    const totalPreguntas = parseInt(totalSpan.textContent);

    function actualizarContador() {
        let respondidas = 0;

        // Recorremos todas las preguntas
        questions.forEach((question, i) => {
            const inputs = question.querySelectorAll('input[type="radio"]');
            for (const input of inputs) {
                if (input.checked) {
                    respondidas++;
                    break; // Salimos del bucle cuando encontramos una opción marcada
                }
            }
        });

        // Actualizamos el DOM
        respondidasSpan.textContent = respondidas;
    }

    // Añadir listeners a todos los radio buttons
    const radios = document.querySelectorAll('input[type="radio"]');
    radios.forEach(radio => {
        radio.addEventListener('change', actualizarContador);
    });

    // Inicializamos el contador al cargar
    actualizarContador();
});

// Inicializar la visualización de la primera pregunta
document.addEventListener('DOMContentLoaded', () => {
    showQuestion(currentQuestionIndex); // Mostrar la primera pregunta al cargar la página
});