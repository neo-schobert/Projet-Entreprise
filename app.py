import os
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime, timedelta
import folium
from folium.plugins import Draw
from sentinelhub import SHConfig, SentinelHubRequest, MimeType, CRS, BBox, DataCollection
from oauthlib.oauth2 import BackendApplicationClient
from requests_oauthlib import OAuth2Session
import numpy as np
from PIL import Image
from esa_snappy import ProductIO, GPF, HashMap
from tkcalendar import DateEntry
from tkinter import PhotoImage


def afficher_carte():
    m = folium.Map(location=[48.8566, 2.3522], zoom_start=5)
    draw = Draw(export=True)
    draw.add_to(m)
    m.save('map.html')
    os.system('open map.html' if os.name == 'posix' else 'start map.html')


def charger_geojson():
    geojson_file = filedialog.askopenfilename(
        title="Sélectionnez le fichier GeoJSON", filetypes=[("GeoJSON files", "*.geojson")])
    if geojson_file:
        entree_zone.delete(0, tk.END)
        entree_zone.insert(0, geojson_file)
    else:
        messagebox.showerror("Erreur", "Aucun fichier GeoJSON sélectionné.")


def configure_sentinel_hub():
    config = SHConfig()
    config.sh_client_id = 'sh-e0de4a21-276f-45de-97b5-8e6ebf1af1cc'
    config.sh_client_secret = 'u8SjN72hFVVDleTvooQ6cRdjaFCE6cns'
    config.sh_base_url = 'https://sh.dataspace.copernicus.eu'
    config.sh_token_url = 'https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token'

    client = BackendApplicationClient(client_id=config.sh_client_id)
    oauth = OAuth2Session(client=client)
    return config


def telecharger_donnees():
    geojson_file = entree_zone.get()
    date_debut = entree_debut.get_date()
    date_fin = entree_fin.get_date()
    nombre_images = entree_nombre_images.get()

    try:
        # Conversion des dates au format string
        date_debut_str = date_debut.strftime('%Y-%m-%d')
        date_fin_str = date_fin.strftime('%Y-%m-%d')

        date_debut_obj = datetime.strptime(date_debut_str, '%Y-%m-%d')
        date_fin_obj = datetime.strptime(date_fin_str, '%Y-%m-%d')
        nombre_images = int(nombre_images)
    except ValueError:
        messagebox.showerror(
            "Erreur", "Format de date invalide ou nombre d'images invalide. Utilisez AAAA-MM-JJ pour les dates et un nombre entier pour les images.")
        return

    if not geojson_file:
        messagebox.showerror(
            "Erreur", "Veuillez sélectionner un fichier GeoJSON.")
        return

    if nombre_images <= 0:
        messagebox.showerror(
            "Erreur", "Le nombre d'images doit être supérieur à zéro.")
        return

    dossier_enregistrement = filedialog.askdirectory(
        title="Choisir le dossier d'enregistrement des images")
    if not dossier_enregistrement:
        messagebox.showerror(
            "Erreur", "Aucun dossier sélectionné pour l'enregistrement.")
        return

    with open(geojson_file, 'r') as file:
        geojson_data = json.load(file)

    config = configure_sentinel_hub()

    # Calculer l'intervalle entre les images
    total_days = (date_fin_obj - date_debut_obj).days
    if total_days <= 0:
        messagebox.showerror(
            "Erreur", "La date de fin doit être après la date de début.")
        return

    intervalle_jours = total_days / \
        (nombre_images - 1) if nombre_images > 1 else total_days

    date_courante = date_debut_obj

    for image_index in range(nombre_images):
        if date_courante > date_fin_obj:
            break
        date_fin_intervalle = date_courante

        # Pour chaque `feature_index`, créer un dossier dans le dossier d'enregistrement
        for feature_index, feature in enumerate(geojson_data['features']):
            # Créer un dossier pour le feature_index
            dossier_feature = os.path.join(
                dossier_enregistrement, f"Zone_{feature_index + 1}")
            os.makedirs(dossier_feature, exist_ok=True)

            geometry = feature['geometry']
            if geometry['type'] == 'Polygon':
                bbox_coords = geometry['coordinates'][0]
                min_x = min(coord[0] for coord in bbox_coords)
                min_y = min(coord[1] for coord in bbox_coords)
                max_x = max(coord[0] for coord in bbox_coords)
                max_y = max(coord[1] for coord in bbox_coords)
                bbox = BBox(bbox=(min_x, min_y, max_x, max_y), crs=CRS.WGS84)
            else:
                messagebox.showerror(
                    "Erreur", "Le fichier GeoJSON ne contient pas un polygone.")
                return

            request = SentinelHubRequest(
                data_folder=None,
                evalscript="""//VERSION=3
                function setup() {
                    return {
                        input: ["VV", "VH"],
                        output: { bands: 1 }
                    };
                }

                function evaluatePixel(sample) {
                    let intensity = (sample.VV + sample.VH) / 2.0;
                    return [Math.sqrt(intensity)];
                }
                """,
                input_data=[SentinelHubRequest.input_data(
                    data_collection=DataCollection.SENTINEL1.define_from(
                        "s1", service_url=config.sh_base_url),
                    time_interval=(date_courante.strftime(
                        '%Y-%m-%d'), (date_courante + timedelta(days=intervalle_jours)).strftime('%Y-%m-%d'))
                )],
                responses=[SentinelHubRequest.output_response(
                    'default', MimeType.TIFF)],
                bbox=bbox,
                size=(2500, 2500),
                config=config
            )

            try:
                response_list = request.get_data()

                for response in response_list:
                    if isinstance(response, np.ndarray):
                        array = response
                        if array.dtype != np.uint8:
                            array = (255 * (array - array.min()) /
                                     (array.max() - array.min())).astype(np.uint8)

                        image = Image.fromarray(array)
                        image_filename = f"{date_courante.strftime('%Y-%m-%d')}.tiff"
                        chemin_image = os.path.join(
                            dossier_feature, image_filename).replace("\\", "/")
                        image.save(chemin_image)

                        print(f"Image enregistrée : {chemin_image}")

            except Exception as e:
                print(f"Erreur lors du téléchargement des données : {e}")
                messagebox.showerror(
                    "Erreur", f"Erreur lors du téléchargement des données : {e}")

        date_courante += timedelta(days=intervalle_jours)


def appliquer_filtre_speckle(image_path, output_path):
    try:
        product = ProductIO.readProduct(image_path)
        parameters = HashMap()
        parameters.put('filter', 'Lee')
        speckle_filtered_product = GPF.createProduct(
            'Speckle-Filter', parameters, product)
        ProductIO.writeProduct(speckle_filtered_product,
                               output_path, 'GeoTIFF')
        messagebox.showinfo(
            "Succès", f"Filtrage speckle appliqué avec succès ! Fichier enregistré : {output_path}")
        print(f"Image filtrée enregistrée : {output_path}")
    except Exception as e:
        messagebox.showerror(
            "Erreur", f"Erreur lors du filtrage speckle : {e}")


def traiter_image():
    fichier_sar = filedialog.askopenfilename(
        title="Sélectionner une image SAR", filetypes=[("Image SAR", "*.tiff")])
    if not fichier_sar:
        messagebox.showerror("Erreur", "Aucune image sélectionnée.")
        return

    dossier_enregistrement = filedialog.askdirectory(
        title="Sélectionner le dossier d'enregistrement")
    if not dossier_enregistrement:
        messagebox.showerror("Erreur", "Aucun dossier sélectionné.")
        return

    nom_fichier_filtre = os.path.basename(
        fichier_sar).replace(".tiff", "_filtre_speckle.tiff")
    chemin_image_filtre = os.path.join(
        dossier_enregistrement, nom_fichier_filtre)
    appliquer_filtre_speckle(fichier_sar, chemin_image_filtre)


def interface_utilisateur():
    fenetre = tk.Tk()
    fenetre.title("Téléchargement Sentinel-1 avec SNAP")
    fenetre.configure(bg='white')

    try:
        icon = PhotoImage(file='icon.png')
        fenetre.iconphoto(True, icon)
    except Exception as e:
        print(f"Erreur lors du chargement de l'icône : {e}")

    # Configuration du style
    style = ttk.Style()
    style.configure('TButton', font=('Helvetica', 12, 'bold'), padding=10,
                    relief='flat', background='#007BFF', foreground='black')
    style.map('TButton', background=[('active', '#0056b3')])
    style.configure('TLabel', font=('Helvetica', 12),
                    background='white', foreground='black')
    style.configure('TEntry', font=('Helvetica', 12), padding=5)
    style.configure('TFrame', background='white')

    # Frame principal
    frame_main = ttk.Frame(fenetre, padding=20)
    frame_main.grid(row=0, column=0, sticky='nsew')

    # Configuration des colonnes et lignes de la grille
    frame_main.grid_columnconfigure(1, weight=1)
    frame_main.grid_rowconfigure(0, weight=1)
    frame_main.grid_rowconfigure(1, weight=0)
    frame_main.grid_rowconfigure(2, weight=0)
    frame_main.grid_rowconfigure(3, weight=0)
    frame_main.grid_rowconfigure(4, weight=0)
    frame_main.grid_rowconfigure(5, weight=0)
    frame_main.grid_rowconfigure(6, weight=0)
    frame_main.grid_rowconfigure(7, weight=0)

    # Titre
    label_titre = ttk.Label(
        frame_main, text="Téléchargement et Traitement des Données Sentinel-1", font=('Helvetica', 16, 'bold'))
    label_titre.grid(row=0, column=0, columnspan=3, pady=10, sticky=tk.W)

    # Bouton pour afficher la carte
    bouton_carte = ttk.Button(
        frame_main, text="Afficher la carte et dessiner une zone", command=afficher_carte)
    bouton_carte.grid(row=1, column=0, columnspan=3, pady=10, sticky=tk.W+tk.E)

    # Zone géographique
    label_zone = ttk.Label(frame_main, text="Zone géographique (GeoJSON) :")
    label_zone.grid(row=2, column=0, pady=10, sticky=tk.W)
    global entree_zone
    entree_zone = ttk.Entry(frame_main, width=50)
    entree_zone.grid(row=2, column=1, pady=10, sticky=tk.W+tk.E)
    bouton_geojson = ttk.Button(
        frame_main, text="Charger un fichier GeoJSON", command=charger_geojson)
    bouton_geojson.grid(row=2, column=2, pady=5, sticky=tk.E)

    # Date de début
    label_debut = ttk.Label(frame_main, text="Date de début :")
    label_debut.grid(row=3, column=0, pady=10, sticky=tk.W)
    global entree_debut
    entree_debut = DateEntry(frame_main, width=20, background='white',
                             foreground='black', borderwidth=2, bordercolor='#007BFF')
    entree_debut.grid(row=3, column=1, pady=10, sticky=tk.W+tk.E)

    # Date de fin
    label_fin = ttk.Label(frame_main, text="Date de fin :")
    label_fin.grid(row=4, column=0, pady=10, sticky=tk.W)
    global entree_fin
    entree_fin = DateEntry(frame_main, width=20, background='white',
                           foreground='black', borderwidth=2, bordercolor='#007BFF')
    entree_fin.grid(row=4, column=1, pady=10, sticky=tk.W+tk.E)

    # Nombre total d'images
    label_nombre_images = ttk.Label(frame_main, text="Nombre total d'images :")
    label_nombre_images.grid(row=5, column=0, pady=10, sticky=tk.W)
    global entree_nombre_images
    entree_nombre_images = ttk.Entry(frame_main, width=20)
    entree_nombre_images.grid(row=5, column=1, pady=10, sticky=tk.W+tk.E)

    # Bouton pour télécharger les données
    bouton_telecharger = ttk.Button(
        frame_main, text="Télécharger les données", command=telecharger_donnees)
    bouton_telecharger.grid(row=6, column=0, columnspan=3,
                            pady=15, sticky=tk.W+tk.E)

    # Bouton pour traiter une image SAR
    bouton_traiter_image = ttk.Button(
        frame_main, text="Traiter une image SAR", command=traiter_image)
    bouton_traiter_image.grid(
        row=7, column=0, columnspan=3, pady=15, sticky=tk.W+tk.E)

    # Dimensionnement automatique de la fenêtre
    fenetre.update_idletasks()
    # Taille minimale pour éviter des réductions excessives
    fenetre.minsize(800, 600)
    fenetre.mainloop()


# Lancer l'interface utilisateur
if __name__ == "__main__":
    interface_utilisateur()
