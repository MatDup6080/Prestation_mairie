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
    def __init__(self, id, nom, prenom, role, mairie_id=None):
        self.id = id
        self.nom = nom
        self.prenom = prenom
        self.role = role
        self.mairie_id = mairie_id 

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
        return Usager(u['id'], u['nom'], u['prenom'], u['role'], u['mairie_id'])
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
            user = Usager(user_data['id'], user_data['nom'], user_data['prenom'], 
                          user_data['role'], user_data['mairie_id'])
            login_user(user)

            # --- LOGIQUE DE REDIRECTION (Bien indentée) ---
            if user.role == 'personnel_mairie':
                return redirect(url_for('espace_mairie'))
            elif user.role == 'referent' or user.role == 'référent':
                return redirect(url_for('dashboard_referent'))
            elif user.role == 'admin_prestataire':
                return redirect(url_for('menu_admin'))
            else:
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

# --- ROUTES ADMIN PRESTATAIRE ---

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

@app.route('/admin/nouvelle-mairie', methods=['GET', 'POST'])
@login_required
def ajouter_mairie():
    conn = get_db_connection()
    
    if request.method == 'POST':
        nom = request.form.get('nom')
        ville = request.form.get('ville')
        
        # Vérification si la mairie existe déjà
        existe = conn.execute('SELECT id FROM mairie WHERE nom = ? AND ville = ?', 
                             (nom, ville)).fetchone()
        
        if existe:
            flash("Erreur : Cette mairie existe déjà dans le système.")
        else:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO mairie (nom, ville) VALUES (?, ?)', (nom, ville))
            mairie_id = cursor.lastrowid
            conn.commit()
            flash(f"Mairie de {ville} créée avec succès.")
            conn.close()
            return redirect(url_for('ajouter_referent', mairie_id=mairie_id))
            
    # On récupère toutes les mairies pour les afficher sous le formulaire
    mairies = conn.execute('SELECT * FROM mairie ORDER BY ville ASC').fetchall()
    conn.close()
    
    return render_template('ajouter_mairie.html', mairies=mairies)
    
@app.route('/admin/supprimer-mairie/<int:mairie_id>', methods=['POST'])
@login_required
def supprimer_mairie(mairie_id):
    # Sécurité : Seul l'admin peut supprimer une mairie
    if current_user.role != 'admin_prestataire':
        flash("Accès refusé.")
        return redirect(url_for('login'))

    conn = get_db_connection()
    
    # Optionnel : Vérifier si la mairie a encore du personnel lié
    personnel = conn.execute('SELECT id FROM usager WHERE mairie_id = ?', (mairie_id,)).fetchone()
    
    if personnel:
        flash("Impossible de supprimer : cette mairie possède encore du personnel ou un référent.")
    else:
        conn.execute('DELETE FROM mairie WHERE id = ?', (mairie_id,))
        conn.commit()
        flash("Mairie supprimée avec succès.")
    
    conn.close()
    return redirect(url_for('ajouter_mairie'))

@app.route('/admin/nouveau-referent/<int:mairie_id>', methods=['GET', 'POST'])
@login_required
def ajouter_referent(mairie_id):
    if request.method == 'POST':
        nom = request.form.get('nom')
        prenom = request.form.get('prenom')
        email = request.form.get('email')
        mdp = request.form.get('mdp')
        
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO usager (nom, prenom, email, mdp, role, mairie_id) 
            VALUES (?, ?, ?, ?, 'referent', ?)
        ''', (nom, prenom, email, mdp, mairie_id))
        conn.commit()
        conn.close()
        
        flash("Compte référent créé avec succès.")
        return redirect(url_for('menu_admin'))
        
    return render_template('ajouter_referent.html', mairie_id=mairie_id)

# --- ROUTES RÉFÉRENT MAIRIE ---

@app.route('/referent/dashboard')
@login_required
def dashboard_referent():
    if current_user.role not in ['referent', 'référent']:
        return redirect(url_for('login'))

    conn = get_db_connection()
    
    # On récupère le nom, prénom, email et SURTOUT le service
    membres = conn.execute('''
        SELECT id, nom, prenom, email, service 
        FROM usager 
        WHERE mairie_id = ? AND role = 'personnel_mairie'
    ''', (current_user.mairie_id,)).fetchall()

    # On récupère aussi les tickets (on garde la jointure pour avoir le service du demandeur)
    tickets = conn.execute('''
        SELECT t.*, u.nom as demandeur, u.service 
        FROM ticket t 
        JOIN usager u ON t.createur_id = u.id 
        WHERE u.mairie_id = ? 
        ORDER BY t.date_creation DESC
    ''', (current_user.mairie_id,)).fetchall()
    
    conn.close()
    return render_template('dashboard_referent.html', membres=membres, tickets=tickets)

@app.route('/referent/ajouter-personnel', methods=['POST'])
@login_required
def ajouter_personnel_referent():
    nom = request.form.get('nom')
    prenom = request.form.get('prenom')
    email = request.form.get('email')
    mdp = request.form.get('mdp')
    service = request.form.get('service')

    conn = get_db_connection()
    conn.execute('''
       INSERT INTO usager (nom, prenom, email, mdp, role, mairie_id, service) 
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (nom, prenom, email, mdp, 'personnel_mairie', current_user.mairie_id, service))
    conn.commit()
    conn.close()
    
    flash("Nouveau personnel mairie ajouté.")
    return redirect(url_for('dashboard_referent'))

@app.route('/referent/supprimer-personnel/<int:user_id>', methods=['POST'])
@login_required
def supprimer_personnel(user_id):
    # Sécurité : seul le référent peut supprimer
    if current_user.role not in ['referent', 'référent']:
        return redirect(url_for('login'))

    conn = get_db_connection()
    
    # On vérifie que le membre appartient bien à la mairie du référent avant de supprimer
    membre = conn.execute('SELECT * FROM usager WHERE id = ? AND mairie_id = ?', 
                         (user_id, current_user.mairie_id)).fetchone()
    
    if membre:
        conn.execute('DELETE FROM usager WHERE id = ?', (user_id,))
        conn.commit()
        flash(f"L'agent {membre['prenom']} {membre['nom']} a été supprimé.")
    else:
        flash("Erreur : Vous n'avez pas l'autorisation de supprimer ce profil.")
        
    conn.close()
    return redirect(url_for('dashboard_referent'))

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

# --- ROUTES AGENTS MAIRIE ---

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
        if current_user.role in ['referent', 'référent']:
            flash("Ticket créé avec succès.")
            return redirect(url_for('dashboard_referent'))
        
        return redirect(url_for('espace_mairie'))
        
    return render_template('nouveau_ticket.html')

if __name__ == '__main__':
    app.run(debug=True)
