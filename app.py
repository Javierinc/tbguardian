# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
from urllib.parse import quote_plus
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv() 
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
# app.config['SQLALCHEMY_DATABASE_URI'] = (
#     f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
#     f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
# )
# app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# Definir modelos
class Grupo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), unique=True, nullable=False)
    puntos = db.Column(db.Integer, default=0)
    registro_fecha = db.Column(db.DateTime, default=datetime.utcnow)
    respuestas = db.relationship('Respuesta', backref='grupo', lazy=True)

class Respuesta(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    grupo_id = db.Column(db.Integer, db.ForeignKey('grupo.id'), nullable=False)
    pregunta_id = db.Column(db.Integer, nullable=False)
    correcta = db.Column(db.Boolean, default=False)
    intentos = db.Column(db.Integer, default=0)
    fecha_correcta = db.Column(db.DateTime, nullable=True)

class SistemaSecuestrado(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), unique=True, nullable=False)
    estado = db.Column(db.String(50), default='Secuestrado')  # Secuestrado o Control Humano

# Respuestas correctas para cada pregunta (en la vida real, esto debería estar en un lugar más seguro)
RESPUESTAS_CORRECTAS = {
    1: "159",
    2: "ACCESO CONCEDIDO",
    3: "6139",
    4: "EL GUARDIAN ACEPTA",
    5: "CCHC"
}

# Crear todas las tablas
with app.app_context():
    db.create_all()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/registrar', methods=['POST'])
def registrar():
    nombre_grupo = request.form.get('nombre_grupo')
    
    if not nombre_grupo:
        flash('Por favor ingresa un nombre de grupo')
        return redirect(url_for('index'))
    
    # Verificar si el grupo ya existe
    grupo_existente = Grupo.query.filter_by(nombre=nombre_grupo).first()
    if grupo_existente:
        flash('Este nombre de grupo ya está registrado')
        return redirect(url_for('index'))
    
    # Crear nuevo grupo
    nuevo_grupo = Grupo(nombre=nombre_grupo)
    db.session.add(nuevo_grupo)
    db.session.commit()
    
    # Guardar en sesión
    # session['grupo_id'] = nuevo_grupo.id
    # session['nombre_grupo'] = nombre_grupo
    session['grupo_id'] = nuevo_grupo.id
    session['nombre_grupo'] = nombre_grupo
    session.permanent = True
    
    # Inicializar respuestas para este grupo
    for i in range(1, 6):
        nueva_respuesta = Respuesta(grupo_id=nuevo_grupo.id, pregunta_id=i)
        db.session.add(nueva_respuesta)
    db.session.commit()
    
    return redirect(url_for('concurso'))

@app.route('/concurso')
def concurso():
    # Verificar si el usuario está "logueado"
    if 'grupo_id' not in session:
        flash('Debes registrarte primero')
        return redirect(url_for('index'))
    
    grupo_id = session['grupo_id']
    grupo = Grupo.query.get_or_404(grupo_id)
    respuestas = Respuesta.query.filter_by(grupo_id=grupo_id).all()
    
    # Obtener las respuestas correctas por pregunta
    respuestas_correctas_por_pregunta = {}
    for i in range(1, 6):
        respuesta = next((r for r in respuestas if r.pregunta_id == i), None)
        respuestas_correctas_por_pregunta[i] = respuesta.correcta if respuesta else False
    
    # Obtener la tabla de posiciones
    grupos = Grupo.query.order_by(Grupo.puntos.desc()).all()
    
    return render_template('concurso.html', 
                          grupo=grupo, 
                          respuestas_correctas=respuestas_correctas_por_pregunta,
                          tabla_posiciones=grupos)

@app.route('/responder', methods=['POST'])
def responder():
    if 'grupo_id' not in session:
        return jsonify({'success': False, 'message': 'Sesión expirada'})
    
    grupo_id = session['grupo_id']
    pregunta_id = int(request.form.get('pregunta_id'))
    respuesta_usuario = request.form.get('respuesta')
    
    # Obtener la respuesta correcta
    respuesta_correcta = RESPUESTAS_CORRECTAS.get(pregunta_id)
    
    # Obtener el registro de respuesta para este grupo y pregunta
    respuesta_registro = Respuesta.query.filter_by(
        grupo_id=grupo_id, 
        pregunta_id=pregunta_id
    ).first()
    
    # Si la respuesta ya fue respondida correctamente
    if respuesta_registro and respuesta_registro.correcta:
        return jsonify({
            'success': False,
            'message': 'Ya has respondido correctamente a esta pregunta'
        })
    
    # Si es una nueva respuesta o un nuevo intento
    if not respuesta_registro:
        respuesta_registro = Respuesta(
            grupo_id=grupo_id, 
            pregunta_id=pregunta_id,
            intentos=1
        )
        db.session.add(respuesta_registro)
    else:
        respuesta_registro.intentos += 1
    
    # Verificar si la respuesta es correcta
    es_correcta = (respuesta_usuario.lower() == respuesta_correcta.lower())
    
    if es_correcta:
        # Marcar como correcta y registrar la fecha
        respuesta_registro.correcta = True
        respuesta_registro.fecha_correcta = datetime.utcnow()
        
        # Obtener la posición para esta respuesta correcta
        respuestas_correctas = Respuesta.query.filter_by(
            pregunta_id=pregunta_id, 
            correcta=True
        ).order_by(Respuesta.fecha_correcta).all()
        
        posicion = next((i+1 for i, r in enumerate(respuestas_correctas) 
                        if r.grupo_id == grupo_id), 0)
        
        # Calcular puntos basados en la posición (100, 90, 80, etc.)
        if pregunta_id == 5:
            puntos_a_otorgar = max(200 - (posicion - 1) * 10, 10)
        else:
            puntos_a_otorgar = max(100 - (posicion - 1) * 10, 10)
        # puntos_a_otorgar = max(100 - (posicion - 1) * 10, 10)  # Mínimo 10 puntos
        
        # Actualizar puntos del grupo
        grupo = Grupo.query.get(grupo_id)
        grupo.puntos += puntos_a_otorgar
        
        db.session.commit()
        mensaje = f'¡Correcto! Han ganado {puntos_a_otorgar} puntos.'
        if pregunta_id == 4:
            mensaje = f'¡Correcto! Han ganado {puntos_a_otorgar} puntos. ¡¡¡AHORA BUSCA BAJO LA MESA!!!'
        if pregunta_id == 5:
            mensaje = f'¡Sistemas desbloqueados! Le ganaron a la IA son geniales 💪 '
        
        return jsonify({
            'success': True,
            'message': mensaje,
            'puntos': puntos_a_otorgar
        })
    else:
        db.session.commit()
        return jsonify({
            'success': False,
            'message': 'Respuesta incorrecta. Inténtalo nuevamente.'
        })


@app.route('/tabla')
def tabla():
    # grupo_id = session['grupo_id']
    # grupo = Grupo.query.get_or_404(grupo_id)
    grupos = Grupo.query.order_by(Grupo.puntos.desc()).all()

    return render_template('posiciones.html',
                           tabla_posiciones=grupos)


@app.route('/posiciones')
def posiciones():
    # Obtener la tabla de posiciones
    grupos = Grupo.query.order_by(Grupo.puntos.desc()).all()
    
    return jsonify({
        'posiciones': [{'nombre': g.nombre, 'puntos': g.puntos} for g in grupos]
    })

@app.route('/sistemas')
def sistemas():
    # Obtener la tabla de posiciones
    sistemas_actuales = SistemaSecuestrado.query.all()
    
    return jsonify({
        'sistemas': [{'id':g.id,'nombre': g.nombre, 'estado': g.estado} for g in sistemas_actuales]
    })

@app.route('/emergencia')
def emergencia():
    sistemas = SistemaSecuestrado.query.all()
    return render_template('sistemas.html',
                           sistemas=sistemas)




@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add_team':
            nombre_grupo = request.form.get('nombre_grupo')
            if nombre_grupo:
                grupo_existente = Grupo.query.filter_by(nombre=nombre_grupo).first()
                if not grupo_existente:
                    nuevo_grupo = Grupo(nombre=nombre_grupo)
                    db.session.add(nuevo_grupo)
                    db.session.commit()
                    flash(f'Equipo "{nombre_grupo}" agregado con éxito.', 'success')
                else:
                    flash('Este equipo ya existe.', 'danger')

        elif action == 'update_score':
            grupo_id = request.form.get('grupo_id')
            nuevo_puntaje = request.form.get('nuevo_puntaje')
            grupo = Grupo.query.get(grupo_id)
            if grupo and nuevo_puntaje.isdigit():
                grupo.puntos = int(nuevo_puntaje)
                db.session.commit()
                flash(f'Puntaje de "{grupo.nombre}" actualizado a {nuevo_puntaje} puntos.', 'success')

        elif action == 'delete_team':
            grupo_id = request.form.get('grupo_id')
            grupo = Grupo.query.get(grupo_id)
            if grupo:
                # Eliminar respuestas asociadas
                Respuesta.query.filter_by(grupo_id=grupo.id).delete()
                
                # Eliminar equipo
                db.session.delete(grupo)
                db.session.commit()
                
                flash(f'Equipo "{grupo.nombre}" eliminado con éxito.', 'success')

        elif action == 'add_system':
            nombre_sistema = request.form.get('nombre_sistema')
            if nombre_sistema:
                sistema_existente = SistemaSecuestrado.query.filter_by(nombre=nombre_sistema).first()
                if not sistema_existente:
                    nuevo_sistema = SistemaSecuestrado(nombre=nombre_sistema, estado="Secuestrado")
                    db.session.add(nuevo_sistema)
                    db.session.commit()
                    print("Sistema agregado correctamente.") 
                    flash(f'Sistema "{nombre_sistema}" agregado con éxito.', 'success')
                else:
                    flash('Este sistema ya existe.', 'danger')

        elif action == 'update_system':
            sistema_id = request.form.get('sistema_id')
            nuevo_estado = request.form.get('nuevo_estado')
            sistema = SistemaSecuestrado.query.get(sistema_id)
            if sistema and nuevo_estado:
                sistema.estado = nuevo_estado
                db.session.commit()
                flash(f'Estado del sistema "{sistema.nombre}" actualizado a {nuevo_estado}.', 'success')

        elif action == 'delete_system':
            sistema_id = request.form.get('sistema_id')
            sistema = SistemaSecuestrado.query.get(sistema_id)
            if sistema:
                db.session.delete(sistema)
                db.session.commit()
                flash(f'Sistema "{sistema.nombre}" eliminado con éxito.', 'success')


        return redirect(url_for('admin'))

    grupos = Grupo.query.order_by(Grupo.puntos.desc()).all()
    sistemas = SistemaSecuestrado.query.all()
    return render_template('admin.html', grupos=grupos, sistemas=sistemas)


if __name__ == '__main__':
    port = int(os.getenv('PORT', 8000))  # Usar el puerto asignado por Railway o 8000 si no está disponible
    app.run(debug=True, host='0.0.0.0', port=port)

# # app.py
# from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
# from flask_sqlalchemy import SQLAlchemy
# from datetime import datetime
# import os

# app = Flask(__name__)
# app.config['SECRET_KEY'] = os.urandom(24)
# app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///concurso.db'
# app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# db = SQLAlchemy(app)

# # Definir modelos
# class Grupo(db.Model):
#     id = db.Column(db.Integer, primary_key=True)
#     nombre = db.Column(db.String(100), unique=True, nullable=False)
#     puntos = db.Column(db.Integer, default=0)
#     registro_fecha = db.Column(db.DateTime, default=datetime.utcnow)
#     respuestas = db.relationship('Respuesta', backref='grupo', lazy=True)

# class Respuesta(db.Model):
#     id = db.Column(db.Integer, primary_key=True)
#     grupo_id = db.Column(db.Integer, db.ForeignKey('grupo.id'), nullable=False)
#     pregunta_id = db.Column(db.Integer, nullable=False)
#     correcta = db.Column(db.Boolean, default=False)
#     intentos = db.Column(db.Integer, default=0)
#     fecha_correcta = db.Column(db.DateTime, nullable=True)

# # Respuestas correctas para cada pregunta (en la vida real, esto debería estar en un lugar más seguro)
# RESPUESTAS_CORRECTAS = {
#     1: "clave1",
#     2: "clave2",
#     3: "clave3",
#     4: "clave4",
#     5: "clave5"
# }

# # Crear todas las tablas
# with app.app_context():
#     db.create_all()

# @app.route('/')
# def index():
#     return render_template('index.html')

# @app.route('/registrar', methods=['POST'])
# def registrar():
#     nombre_grupo = request.form.get('nombre_grupo')
    
#     if not nombre_grupo:
#         flash('Por favor ingresa un nombre de grupo')
#         return redirect(url_for('index'))
    
#     # Verificar si el grupo ya existe
#     grupo_existente = Grupo.query.filter_by(nombre=nombre_grupo).first()
#     if grupo_existente:
#         flash('Este nombre de grupo ya está registrado')
#         return redirect(url_for('index'))
    
#     # Crear nuevo grupo
#     nuevo_grupo = Grupo(nombre=nombre_grupo)
#     db.session.add(nuevo_grupo)
#     db.session.commit()
    
#     # Guardar en sesión
#     session['grupo_id'] = nuevo_grupo.id
#     session['nombre_grupo'] = nombre_grupo
    
#     # Inicializar respuestas para este grupo
#     for i in range(1, 6):
#         nueva_respuesta = Respuesta(grupo_id=nuevo_grupo.id, pregunta_id=i)
#         db.session.add(nueva_respuesta)
#     db.session.commit()
    
#     return redirect(url_for('concurso'))

# @app.route('/concurso')
# def concurso():
#     # Verificar si el usuario está "logueado"
#     if 'grupo_id' not in session:
#         flash('Debes registrarte primero')
#         return redirect(url_for('index'))
    
#     grupo_id = session['grupo_id']
#     grupo = Grupo.query.get_or_404(grupo_id)
#     respuestas = Respuesta.query.filter_by(grupo_id=grupo_id).all()
    
#     # Obtener las respuestas correctas por pregunta
#     respuestas_correctas_por_pregunta = {}
#     for i in range(1, 6):
#         respuesta = next((r for r in respuestas if r.pregunta_id == i), None)
#         respuestas_correctas_por_pregunta[i] = respuesta.correcta if respuesta else False
    
#     return render_template('concurso.html', 
#                           grupo=grupo, 
#                           respuestas_correctas=respuestas_correctas_por_pregunta)

# @app.route('/posiciones')
# def posiciones_view():
#     # Si hay un grupo en sesión, obtenemos sus datos
#     grupo_actual = None
#     if 'grupo_id' in session:
#         grupo_actual = Grupo.query.get(session['grupo_id'])
    
#     # Obtener la tabla de posiciones
#     grupos = Grupo.query.order_by(Grupo.puntos.desc()).all()
    
#     return render_template('posiciones.html', 
#                           tabla_posiciones=grupos,
#                           grupo_actual=grupo_actual)

# @app.route('/responder', methods=['POST'])
# def responder():
#     if 'grupo_id' not in session:
#         return jsonify({'success': False, 'message': 'Sesión expirada'})
    
#     grupo_id = session['grupo_id']
#     pregunta_id = int(request.form.get('pregunta_id'))
#     respuesta_usuario = request.form.get('respuesta')
    
#     # Obtener la respuesta correcta
#     respuesta_correcta = RESPUESTAS_CORRECTAS.get(pregunta_id)
    
#     # Obtener el registro de respuesta para este grupo y pregunta
#     respuesta_registro = Respuesta.query.filter_by(
#         grupo_id=grupo_id, 
#         pregunta_id=pregunta_id
#     ).first()
    
#     # Si la respuesta ya fue respondida correctamente
#     if respuesta_registro and respuesta_registro.correcta:
#         return jsonify({
#             'success': False,
#             'message': 'Ya has respondido correctamente a esta pregunta'
#         })
    
#     # Si es una nueva respuesta o un nuevo intento
#     if not respuesta_registro:
#         respuesta_registro = Respuesta(
#             grupo_id=grupo_id, 
#             pregunta_id=pregunta_id,
#             intentos=1
#         )
#         db.session.add(respuesta_registro)
#     else:
#         respuesta_registro.intentos += 1
    
#     # Verificar si la respuesta es correcta
#     es_correcta = (respuesta_usuario.lower() == respuesta_correcta.lower())
    
#     if es_correcta:
#         # Marcar como correcta y registrar la fecha
#         respuesta_registro.correcta = True
#         respuesta_registro.fecha_correcta = datetime.utcnow()
        
#         # Obtener la posición para esta respuesta correcta
#         respuestas_correctas = Respuesta.query.filter_by(
#             pregunta_id=pregunta_id, 
#             correcta=True
#         ).order_by(Respuesta.fecha_correcta).all()
        
#         posicion = next((i+1 for i, r in enumerate(respuestas_correctas) 
#                         if r.grupo_id == grupo_id), 0)
        
#         # Calcular puntos basados en la posición (100, 90, 80, etc.)
#         puntos_a_otorgar = max(100 - (posicion - 1) * 10, 10)  # Mínimo 10 puntos
        
#         # Actualizar puntos del grupo
#         grupo = Grupo.query.get(grupo_id)
#         grupo.puntos += puntos_a_otorgar
        
#         db.session.commit()
        
#         return jsonify({
#             'success': True,
#             'message': f'¡Correcto! Has ganado {puntos_a_otorgar} puntos.',
#             'puntos': puntos_a_otorgar
#         })
#     else:
#         db.session.commit()
#         return jsonify({
#             'success': False,
#             'message': 'Respuesta incorrecta. Inténtalo nuevamente.'
#         })

# @app.route('/api/posiciones')
# def posiciones_api():
#     # Obtener la tabla de posiciones
#     grupos = Grupo.query.order_by(Grupo.puntos.desc()).all()
    
#     return jsonify({
#         'posiciones': [{'nombre': g.nombre, 'puntos': g.puntos, 'id': g.id} for g in grupos]
#     })

# if __name__ == '__main__':
#     app.run(debug=True)

