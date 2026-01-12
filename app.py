from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3

app = Flask(__name__)
app.config['SECRET_KEY'] = 'votre_cle_secrete'

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- Modèle Utilisateur ---
class Usager(UserMixin):
    def __init__(self, id, nom, prenom, role):
        self.id = id
        self.nom = nom
        self.prenom = prenom
        self.role = role

def get_db_connection():
    conn = sqlite3.connect('mairie.db')
    conn.row_factory = sqlite3.Row
    return conn

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    u = conn.execute('SELECT * FROM usager WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    if u:
        return Usager(u['id'], u['nom'], u['prenom'], u['role'])
    return None

# --- ROUTES ---

@app.route('/', methods=['GET', 'POST']) # Ajout impératif de methods
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        mdp = request.form.get('mdp')
        
        conn = get_db_connection()
        user_data = conn.execute('SELECT * FROM usager WHERE email = ? AND mdp = ?', 
                                (email, mdp)).fetchone()
        conn.close()
        
        if user_data:
            # On crée l'objet utilisateur avec les 4 paramètres attendus par ton __init__
            user = Usager(user_data['id'], user_data['nom'], user_data['prenom'], user_data['role'])
            login_user(user)
            
            # Redirection selon le rôle
            if user.role == 'personnel_mairie':
                return redirect(url_for('espace_mairie'))
            return redirect(url_for('menu_admin'))
        else:
            flash("Identifiants incorrects")
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Vous avez été déconnecté.")
    return redirect(url_for('login'))

@app.route('/admin/assigner/<int:ticket_id>', methods=['POST'])
@login_required
def assigner_ticket(ticket_id):
    tech_id = request.form.get('technicien_id')
    conn = get_db_connection()
    conn.execute('UPDATE ticket SET technicien_id = ?, statut = "En cours" WHERE id = ?', (tech_id, ticket_id))
    conn.commit()
    conn.close()
    return redirect(url_for('prestations_admin'))

@app.route('/admin/update_statut/<int:ticket_id>', methods=['POST'])
@login_required
def update_statut(ticket_id):
    nouveau_statut = request.form.get('statut')
    conn = get_db_connection()
    conn.execute('UPDATE ticket SET statut = ? WHERE id = ?', (nouveau_statut, ticket_id))
    conn.commit()
    conn.close()
    return redirect(url_for('prestations_admin'))

@app.route('/admin/prestations')
@login_required
def prestations_admin():
    conn = get_db_connection()
    tickets = conn.execute('''
        SELECT t.*, strftime('%d/%m/%Y', t.date_creation) as date_formatee, 
        u.nom as demandeur, u.service FROM ticket t 
        JOIN usager u ON t.createur_id = u.id ORDER BY t.date_creation DESC
    ''').fetchall()
    techniciens = conn.execute('SELECT id, prenom FROM usager WHERE role IS NULL').fetchall()
    conn.close()
    return render_template('dashboard_admin.html', tickets=tickets, techniciens=techniciens)

@app.route('/admin/menu')
@login_required
def menu_admin():
    return render_template('menu_admin.html')

@app.route('/admin/inventaire')
@login_required
def inventaire_admin():
    conn = get_db_connection()
    # On récupère le matériel stocké dans la table inventaire
    materiels = conn.execute('SELECT * FROM inventaire').fetchall()
    conn.close()
    return render_template('inventaire_admin.html', materiels=materiels)

if __name__ == '__main__':
    app.run(debug=True)
