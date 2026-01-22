from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3
import unicodedata
import re
import random
import string

app = Flask(__name__)
app.config['SECRET_KEY'] = 'votre_cle_secrete'

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
def simplifier_chaine(texte):
    """Supprime les accents, espaces et met en minuscule."""
    if not texte: return ""
    texte = unicodedata.normalize('NFD', texte)
    texte = "".join([c for c in texte if unicodedata.category(c) != 'Mn']).lower()
    return texte.replace(" ", "")

def valider_format_strict_email(email, prenom, nom):
    """Vérifie le format prenom.nom@... ou p.nom@... avec domaines .fr ou gmail.com"""
    email = email.lower().strip()
    p = simplifier_chaine(prenom)
    n = simplifier_chaine(nom)
    
    format1 = f"{p}.{n}"          # prenom.nom
    format2 = f"{p[0]}.{n}"       # p.nom
    
    # Regex : accepte gmail.com ou n'importe quel domaine finissant par .fr
    suffixe_pattern = r"@(gmail\.com|[a-zA-Z0-9-]+\.fr)$"
    pattern = f"^({re.escape(format1)}|{re.escape(format2)}){suffixe_pattern}"
    
    return re.match(pattern, email) is not None
# --- Modèle Utilisateur ---
class Usager(UserMixin):
     def __init__(self, id, nom, prenom, role, mairie_id=None, premier_login=1):
        self.id = id
        self.nom = nom
        self.prenom = prenom
        self.role = role
        self.mairie_id = mairie_id
        self.premier_login = premier_login

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
        return Usager(u['id'], u['nom'], u['prenom'], u['role'], u['mairie_id'],u['premier_login'])
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
                          user_data['role'], user_data['mairie_id'], user_data['premier_login'])
            login_user(user)

            # --- LOGIQUE DE PREMIÈRE CONNEXION ---
            if user.premier_login == 1:
                flash("Ceci est votre première connexion. Veuillez sécuriser votre compte en changeant votre mot de passe.")
                return redirect(url_for('modifier_mdp'))

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
    conn.execute("DELETE FROM ticket WHERE statut = 'Terminé' AND date_fin < datetime('now', '-30 days')")
    conn.commit()
    # On ajoute "LEFT JOIN usager AS tech" pour récupérer les infos du technicien
    tickets = conn.execute('''
        SELECT t.*, 
               strftime('%d/%m/%Y', t.date_creation) as date_formatee, 
               u.nom as demandeur, 
               u.service,
               tech.prenom as tech_prenom,
               tech.nom as tech_nom
        FROM ticket t 
        JOIN usager u ON t.createur_id = u.id 
        LEFT JOIN usager tech ON t.technicien_id = tech.id
        ORDER BY t.date_creation DESC
    ''').fetchall()
    
    # On s'assure de récupérer les techniciens pour le menu déroulant
    # Note: J'ai changé 'IS NULL' par 'technicien' si vous utilisez des rôles
    techniciens = conn.execute('''
        SELECT u.id, u.prenom, u.nom,
               (SELECT COUNT(t.id) FROM ticket t 
                WHERE t.technicien_id = u.id 
                AND t.statut != 'Terminé') as charge
        FROM usager u 
        WHERE u.role = 'technicien' OR u.role IS NULL
    ''').fetchall()
    conn.close()
    return render_template('dashboard_admin.html', tickets=tickets, techniciens=techniciens)
@app.route('/admin/assigner/<int:ticket_id>', methods=['POST'])
@login_required
def assigner_ticket(ticket_id):
    tech_id = request.form.get('technicien_id')
    contrat = request.form.get('contrat')

    # Dictionnaire de correspondance des durées
    durées = {
        'Gold': '4 heures',
        'Silver': '24 heures',
        'Bronze': '72 heures'
    }
    
    # On récupère la durée correspondante (ou "Non définie" par sécurité)
    duree_intervention = durées.get(contrat, 'Non définie')

    conn = get_db_connection()
    # On ajoute la durée dans la mise à jour (assurez-vous d'avoir la colonne 'duree' en BDD)
    conn.execute('''
        UPDATE ticket 
        SET technicien_id = ?, contrat = ?, duree = ?, statut = "En cours" 
        WHERE id = ?
    ''', (tech_id, contrat, duree_intervention, ticket_id))
    
    conn.commit()
    conn.close()
    flash(f"Assigné en contrat {contrat} (Délai : {duree_intervention})")
    return redirect(url_for('prestations_admin'))


@app.route('/admin/update_statut/<int:ticket_id>', methods=['POST'])
@login_required
def update_statut(ticket_id):
    nouveau_statut = request.form.get('statut')
    conn = get_db_connection()
    
    # Si on veut terminer, on ne met pas "Terminé" tout de suite
    # On met un statut intermédiaire
    if nouveau_statut == 'Terminé':
        conn.execute('''
            UPDATE ticket SET statut = "En attente de validation" WHERE id = ?
        ''', (ticket_id,))
        flash("Ticket mis en attente de confirmation par le client.")
    else:
        conn.execute('UPDATE ticket SET statut = ?, date_fin = NULL WHERE id = ?', 
                    (nouveau_statut, ticket_id))
        flash(f"Statut mis à jour : {nouveau_statut}")
    
    conn.commit()
    conn.close()
    return redirect(url_for('prestations_admin'))
    
@app.route('/mairie/confirmer-cloture/<int:ticket_id>', methods=['POST'])
@login_required
def confirmer_cloture(ticket_id):
    conn = get_db_connection()
    # On vérifie que le ticket appartient bien à l'utilisateur ou sa mairie
    conn.execute('''
        UPDATE ticket 
        SET statut = 'Terminé', date_fin = CURRENT_TIMESTAMP 
        WHERE id = ?
    ''', (ticket_id,))
    conn.commit()
    conn.close()
    flash("✅ Merci ! Le ticket est maintenant clôturé officiellement.")
    return redirect(request.referrer)
    
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
        
        # Validation du format d'email
        if not valider_format_strict_email(email, prenom, nom):
            flash(f"Format d'email invalide. Utilisez {prenom.lower()}.{nom.lower()}@... (gmail.com ou .fr)")
            return redirect(url_for('ajouter_referent', mairie_id=mairie_id))

        conn = get_db_connection()
        try:
            conn.execute('''
                INSERT INTO usager (nom, prenom, email, mdp, role, mairie_id) 
                VALUES (?, ?, ?, ?, 'referent', ?)
            ''', (nom, prenom, email, mdp, mairie_id))
            conn.commit()
            flash("Compte référent créé avec succès.")
        except sqlite3.IntegrityError:
            flash("Erreur : Cette adresse email est déjà utilisée.")
        finally:
            conn.close()
        
        return redirect(url_for('menu_admin'))
        
    return render_template('ajouter_referent.html', mairie_id=mairie_id)

@app.route('/admin/equipe', methods=['GET', 'POST'])
@login_required
def gestion_equipe():
    # Sécurité : seul l'admin prestataire peut accéder
    if current_user.role != 'admin_prestataire':
        flash("Accès refusé.")
        return redirect(url_for('login'))

    conn = get_db_connection()

    if request.method == 'POST':
        nom = request.form.get('nom')
        prenom = request.form.get('prenom')
        email = request.form.get('email')
        mdp = request.form.get('mdp')
        role = request.form.get('role') # 'technicien' ou 'admin_prestataire'

        # Validation de l'email (on réutilise votre logique)
        if not valider_format_strict_email(email, prenom, nom):
            flash("L'email doit respecter le format prenom.nom@... (.fr ou gmail.com)")
        else:
            try:
                conn.execute('''
                    INSERT INTO usager (nom, prenom, email, mdp, role, premier_login) 
                    VALUES (?, ?, ?, ?, ?, 1)
                ''', (nom, prenom, email, mdp, role))
                conn.commit()
                flash(f"Membre {prenom} {nom} ajouté avec succès !")
            except sqlite3.IntegrityError:
                flash("Erreur : Cet email est déjà utilisé.")

    # Récupérer tous les membres de l'équipe prestataire
    equipe = conn.execute('''
        SELECT id, nom, prenom, email, role 
        FROM usager 
        WHERE role IN ('technicien', 'admin_prestataire')
    ''').fetchall()
    
    conn.close()
    return render_template('gestion_equipe.html', equipe=equipe)
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

    # Validation du format d'email
    if not valider_format_strict_email(email, prenom, nom):
        flash("L'email doit correspondre au nom/prénom et finir par gmail.com ou .fr")
        return redirect(url_for('dashboard_referent'))

    conn = get_db_connection()
    try:
        conn.execute('''
           INSERT INTO usager (nom, prenom, email, mdp, role, mairie_id, service) 
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (nom, prenom, email, mdp, 'personnel_mairie', current_user.mairie_id, service))
        conn.commit()
        flash("Nouveau personnel mairie ajouté.")
    except sqlite3.IntegrityError:
        flash("Erreur : Cet email existe déjà.")
    finally:
        conn.close()
    
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

from datetime import datetime

@app.template_filter('to_datetime')
def to_datetime_filter(s):
    if not s: return None
    try:
        # SQLite stocke souvent sous ce format : 2023-10-27 14:30:00
        return datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
    except:
        return None
        
from flask import send_file
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import io
@app.route('/admin/rapport-mensuel')
@login_required
def generer_rapport_pdf():
    conn = get_db_connection()
    
    # Requête complète pour avoir toutes les infos avant suppression
    tickets = conn.execute('''
        SELECT t.*, 
               u.nom as demandeur, 
               m.nom as nom_mairie, 
               m.ville as ville_mairie,
               tech.prenom as tech_prenom, 
               tech.nom as tech_nom
        FROM ticket t
        JOIN usager u ON t.createur_id = u.id
        JOIN mairie m ON u.mairie_id = m.id
        LEFT JOIN usager tech ON t.technicien_id = tech.id
        WHERE strftime('%m', t.date_creation) = strftime('%m', 'now')
    ''').fetchall()

    # --- NETTOYAGE APRÈS RÉCUPÉRATION ---
    # On supprime les tickets terminés de plus de 30 jours
    conn.execute("DELETE FROM ticket WHERE statut = 'Terminé' AND date_fin < datetime('now', '-30 days')")
    conn.commit()
    conn.close()

    # --- GÉNÉRATION DU PDF ---
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=18)
    elements = []
    styles = getSampleStyleSheet()

    # Titre avec le mois actuel
    import datetime
    mois_actuel = datetime.datetime.now().strftime("%B %Y")
    elements.append(Paragraph(f"Rapport d'Interventions - {mois_actuel}", styles['Title']))
    elements.append(Spacer(1, 12))

    # Entête du tableau (ajout de la colonne Mairie)
    data = [['Date', 'Mairie / Ville', 'Sujet', 'Intervenant', 'Contrat', 'SLA']]
    
    for t in tickets:
        # Calcul du SLA
        sla_info = "OK"
        if t['statut'] == 'Terminé' and t['date_fin']:
            # Utilisation de notre logique de calcul de délai
            debut = datetime.datetime.strptime(t['date_creation'], '%Y-%m-%d %H:%M:%S')
            fin = datetime.datetime.strptime(t['date_fin'], '%Y-%m-%d %H:%M:%S')
            diff = (fin - debut).total_seconds() / 3600
            limite = 4 if t['contrat'] == 'Gold' else 24 if t['contrat'] == 'Silver' else 72
            if diff > limite:
                sla_info = f"RETARD (+{int(diff-limite)}h)"

        data.append([
            t['date_creation'][:10],
            f"{t['nom_mairie']}\n({t['ville_mairie']})",
            t['titre'][:20],
            f"{t['tech_prenom']} {t['tech_nom'][0] if t['tech_nom'] else ''}.",
            t['contrat'] if t['contrat'] else "-",
            sla_info
        ])

    # Configuration du tableau (ajustement des largeurs)
    table = Table(data, colWidths=[60, 100, 110, 90, 60, 80])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.whitesmoke])
    ]))
    
    elements.append(table)
    doc.build(elements)
    
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"Rapport_{mois_actuel}.pdf", mimetype='application/pdf')


def valider_securite_mdp(mdp):
    """
    Vérifie la force du mot de passe :
    - 8 caractères minimum
    - Au moins une majuscule
    - Au moins une minuscule
    - Au moins un chiffre
    - Au moins un caractère spécial (@$!%*?&)
    """
    pattern = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$"
    return re.match(pattern, mdp) is not None

@app.route('/profil/modifier-mdp', methods=['GET', 'POST'])
@login_required
def modifier_mdp():
    if request.method == 'POST':
        nouveau_mdp = request.form.get('nouveau_mdp')
        confirmation = request.form.get('confirmation_mdp')

        if nouveau_mdp != confirmation:
            flash("❌ Les mots de passe ne correspondent pas.")
            return redirect(url_for('modifier_mdp'))

        if not valider_securite_mdp(nouveau_mdp):
            flash("❌ Le mot de passe n'est pas assez sécurisé.")
            return redirect(url_for('modifier_mdp'))

        conn = get_db_connection()
        # CETTE LIGNE EST CRUCIALE : on change le MDP ET on passe premier_login à 0
        conn.execute('''
            UPDATE usager 
            SET mdp = ?, premier_login = 0 
            WHERE id = ?
        ''', (nouveau_mdp, current_user.id))
        
        conn.commit()
        conn.close()

        flash("✅ Mot de passe mis à jour ! Veuillez vous reconnecter.")
        return redirect(url_for('logout')) # On déconnecte pour valider le nouveau MDP

    return render_template('modifier_mdp.html')

@app.route('/mot-de-passe-oublie', methods=['GET', 'POST'])
def mdp_oublie():
    if request.method == 'POST':
        email = request.form.get('email')
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM usager WHERE email = ?', (email,)).fetchone()
        
        if user:
            # Génération d'un code de 6 caractères
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            conn.execute('UPDATE usager SET code_recup = ? WHERE email = ?', (code, email))
            conn.commit()
            conn.close()
            
            # Simulation d'envoi de mail via Flash
            flash(f"🔑 [SIMULATION MAIL] Votre code de récupération est : {code}")
            return redirect(url_for('reinitialiser_mdp', email=email))
        
        conn.close()
        flash("Si cet email est reconnu, un code vous a été envoyé.")
        return redirect(url_for('login'))
        
    return render_template('mdp_oublie_demande.html')

@app.route('/reinitialiser-mdp/<email>', methods=['GET', 'POST'])
def reinitialiser_mdp(email):
    if request.method == 'POST':
        code_saisi = request.form.get('code')
        nouveau_mdp = request.form.get('nouveau_mdp')
        confirmation = request.form.get('confirmation_mdp')
        
        if nouveau_mdp != confirmation:
            flash("❌ Les mots de passe ne correspondent pas.")
            return redirect(url_for('reinitialiser_mdp', email=email))

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM usager WHERE email = ? AND code_recup = ?', 
                            (email, code_saisi.upper())).fetchone()
        
        if user:
            if valider_securite_mdp(nouveau_mdp):
                # Mise à jour du MDP et suppression du code temporaire
                conn.execute('UPDATE usager SET mdp = ?, code_recup = NULL WHERE email = ?', 
                             (nouveau_mdp, email))
                conn.commit()
                conn.close()
                flash("✅ Mot de passe réinitialisé ! Vous pouvez vous connecter.")
                return redirect(url_for('login'))
            else:
                flash("❌ Le mot de passe ne respecte pas les règles de sécurité.")
        else:
            flash("❌ Code de validation incorrect.")
        conn.close()
            
    return render_template('mdp_oublie_reset.html', email=email)
    
    
    

    
   
if __name__ == '__main__':
    app.run(debug=True)
