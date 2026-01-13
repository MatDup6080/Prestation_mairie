from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3

app = Flask(__name__)
app.config['SECRET_KEY'] = 'votre_cle_secrete'

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

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

# --- ROUTES DE CONNEXION ---

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        mdp = request.form.get('mdp')
        
        conn = get_db_connection()
        user_data = conn.execute('SELECT * FROM usager WHERE email = ? AND mdp = ?', 
                                (email, mdp)).fetchone()
        conn.close()
        
        if user_data:
            user = Usager(user_data['id'], user_data['nom'], user_data['prenom'], user_data['role'])
            login_user(user)
            
            # LOGIQUE DE REDIRECTION CORRIGÉE
            if user.role == 'personnel_mairie':
                return redirect(url_for('espace_mairie'))
            elif user.nom == 'Administrateur': # Ou un autre critère pour l'admin
                return redirect(url_for('menu_admin'))
            else:
                # C'est un technicien (role est NULL ou autre)
                return redirect(url_for('dashboard_technicien'))
        else:
            flash("Identifiants incorrects")
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Vous avez été déconnecté.")
    return redirect(url_for('login'))

# --- ROUTES ADMIN ---

@app.route('/admin/menu')
@login_required
def menu_admin():
    return render_template('menu_admin.html')

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
    # On redirige vers la page d'où vient l'utilisateur (Admin ou Tech)
    if current_user.nom == 'Administrateur':
        return redirect(url_for('prestations_admin'))
    return redirect(url_for('dashboard_technicien'))

@app.route('/admin/inventaire')
@login_required
def inventaire_admin():
    conn = get_db_connection()
    materiels = conn.execute('SELECT * FROM inventaire').fetchall()
    conn.close()
    return render_template('inventaire_admin.html', materiels=materiels)

# --- ROUTES TECHNICIEN ---

@app.route('/technicien/mes-tickets')
@login_required
def dashboard_technicien():
    conn = get_db_connection()
    mes_interventions = conn.execute('''
        SELECT t.*, strftime('%d/%m/%Y', t.date_creation) as date_formatee, 
               u.nom as demandeur, u.service 
        FROM ticket t 
        JOIN usager u ON t.createur_id = u.id 
        WHERE t.technicien_id = ? 
        ORDER BY t.date_creation DESC
    ''', (current_user.id,)).fetchall()
    conn.close()
    return render_template('dashboard_technicien.html', tickets=mes_interventions)

# --- ROUTES MAIRIE (AGENTS) ---

@app.route('/mairie/dashboard')
@login_required
def espace_mairie():
    conn = get_db_connection()
    mes_tickets = conn.execute('SELECT *, strftime("%d/%m/%Y", date_creation) as date_formatee FROM ticket WHERE createur_id = ? ORDER BY date_creation DESC', 
                               (current_user.id,)).fetchall()
    conn.close()
    return render_template('espace_mairie.html', tickets=mes_tickets)

@app.route('/mairie/nouveau-ticket', methods=['GET', 'POST'])
@login_required
def nouveau_ticket():
    if request.method == 'POST':
        titre = request.form['titre']
        description = request.form['description']
        type_p = request.form['type_prestation']
        
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO ticket (titre, description, type_prestation, createur_id, statut) 
            VALUES (?, ?, ?, ?, ?)
        ''', (titre, description, type_p, current_user.id, 'Nouveau'))
        conn.commit()
        conn.close()
        return redirect(url_for('espace_mairie'))
        
    return render_template('nouveau_ticket.html')

if __name__ == '__main__':
    app.run(debug=True)
