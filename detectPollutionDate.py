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
from PIL import Image, ImageDraw
from esa_snappy import ProductIO, GPF, HashMap
from tkcalendar import DateEntry
from tkinter import PhotoImage
from shapely.geometry import shape, Polygon


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

    try:
        date_debut_str = date_debut.strftime('%Y-%m-%d')
        date_fin_str = date_fin.strftime('%Y-%m-%d')

        date_debut_obj = datetime.strptime(date_debut_str, '%Y-%m-%d')
        date_fin_obj = datetime.strptime(date_fin_str, '%Y-%m-%d')
    except ValueError:
        messagebox.showerror(
            "Erreur", "Format de date invalide. Utilisez AAAA-MM-JJ pour les dates.")
        return

    if not geojson_file:
        messagebox.showerror(
            "Erreur", "Veuillez sélectionner un fichier GeoJSON.")
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

    if (date_fin_obj - date_debut_obj).days <= 0:
        messagebox.showerror(
            "Erreur", "La date de fin doit être après la date de début.")
        return

    def telecharger_image(date_obj, feature, dossier_feature, bbox):
        """Télécharge une image pour une date et une zone spécifique."""
        request = SentinelHubRequest(
            evalscript="""//VERSION=3
            function setup() {
              return {
                input: ["VV", "VH", "dataMask"],
                output: { bands: 4 }
              };
            }
            function evaluatePixel(sample) {
              return [2.5 * sample.VV, 2.5 * sample.VH, 2.5 * sample.VV, sample.dataMask];
            }""",
            input_data=[SentinelHubRequest.input_data(
                data_collection=DataCollection.SENTINEL1,
                time_interval=(date_obj.strftime('%Y-%m-%d'),
                               date_obj.strftime('%Y-%m-%d'))
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
                    array = (255 * (response - response.min()) /
                             (response.max() - response.min())).astype(np.uint8)
                    image = Image.fromarray(array)
                    chemin_image = os.path.join(
                        dossier_feature, f"{date_obj.strftime('%Y-%m-%d')}.tiff")
                    image.save(chemin_image)
                    return chemin_image
        except Exception as e:
            messagebox.showerror(
                "Erreur", f"Erreur lors du téléchargement des données : {e}")
            return None

    def dichotomie_pollution(date_start, date_end, feature, dossier_feature, bbox):
        """Effectue une recherche binaire sur les dates pour trouver la pollution."""
        while date_start < date_end:
            date_mid = date_start + (date_end - date_start) // 2
            chemin_image_debut = telecharger_image(
                date_start, feature, dossier_feature, bbox)
            chemin_image_fin = telecharger_image(
                date_end, feature, dossier_feature, bbox)

            if chemin_image_debut and isPollutionOnImage(chemin_image_debut):
                date_end = date_mid  # La pollution est détectée, on réduit vers le début
            elif chemin_image_fin and isPollutionOnImage(chemin_image_fin):
                # Pollution détectée vers la fin
                date_start = date_mid + timedelta(days=1)
            else:
                # Si aucune image n'a de pollution, on abandonne l'intervalle
                return

    for feature_index, feature in enumerate(geojson_data['features']):
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

        dichotomie_pollution(date_debut_obj, date_fin_obj,
                             feature, dossier_feature, bbox)

# def appliquer_filtres(images_paths, output_paths):
#     try:
#         # Charger les images SAR
#         products = [ProductIO.readProduct(image_path)
#                     for image_path in images_paths]

#         # Étape 1: Calibration (appliquée uniformément sur toutes les images)
#         parameters = HashMap()
#         parameters.put('outputSigmaBand', True)

#         calibrated_products = []
#         for product in products:
#             calibrated_product = GPF.createProduct(
#                 'Calibration', parameters, product)
#             calibrated_products.append(calibrated_product)
#         print("Calibration appliquée à toutes les images")

#         # Étape 2: Déburst (appliqué après la calibration)
#         debursted_products = []
#         for product in calibrated_products:
#             parameters = HashMap()
#             debursted_product = GPF.createProduct(
#                 'TOPSAR-Deburst', parameters, product)
#             debursted_products.append(debursted_product)
#         print("Déburst appliqué à toutes les images")

#         # Étape 3: Co-registration en utilisant la première image comme référence
#         master_product = debursted_products[0]
#         coregistered_products = [master_product]

#         for slave_product in debursted_products[1:]:
#             parameters = HashMap()
#             parameters.put('masterBands', 'Sigma0_VV')
#             parameters.put('slaveBands', 'Sigma0_VV')
#             coregistered_product = GPF.createProduct(
#                 'Back-Geocoding', parameters, [master_product, slave_product])
#             coregistered_products.append(coregistered_product)
#         print("Co-registration appliquée à toutes les images")

#         # Étape 4: Filtrage speckle (appliqué après co-registration)
#         speckle_filtered_products = []
#         for product in coregistered_products:
#             parameters = HashMap()
#             parameters.put('filter', 'Lee')
#             speckle_filtered_product = GPF.createProduct(
#                 'Speckle-Filter', parameters, product)
#             speckle_filtered_products.append(speckle_filtered_product)
#         print("Filtrage speckle appliqué à toutes les images")

#         # Étape 5: Correction de terrain (Range-Doppler)
#         final_products = []
#         for product in speckle_filtered_products:
#             parameters = HashMap()
#             parameters.put('demName', 'SRTM 3Sec')
#             parameters.put('pixelSpacingInMeter', 10.0)
#             parameters.put('sourceBands', 'Sigma0_VV')
#             terrain_corrected_product = GPF.createProduct(
#                 'Terrain-Correction', parameters, product)
#             final_products.append(terrain_corrected_product)
#         print("Correction de terrain appliquée à toutes les images")

#         # Enregistrement des produits finaux
#         for final_product, output_path in zip(final_products, output_paths):
#             ProductIO.writeProduct(final_product, output_path, 'GeoTIFF')
#             print(f"Image traitée enregistrée : {output_path}")

#         messagebox.showinfo(
#             "Succès", "Traitement complet appliqué avec succès !")

#     except Exception as e:
#         messagebox.showerror(
#             "Erreur", f"Erreur lors du traitement des images : {e}")


# def traiter_image():
#     fichier_sar = filedialog.askopenfilename(
#         title="Sélectionner une image SAR", filetypes=[("Image SAR", "*.tiff")])
#     if not fichier_sar:
#         messagebox.showerror("Erreur", "Aucune image sélectionnée.")
#         return

#     dossier_enregistrement = filedialog.askdirectory(
#         title="Sélectionner le dossier d'enregistrement")
#     if not dossier_enregistrement:
#         messagebox.showerror("Erreur", "Aucun dossier sélectionné.")
#         return

#     nom_fichier_filtre = os.path.basename(
#         fichier_sar).replace(".tiff", "_filtre_speckle.tiff")
#     chemin_image_filtre = os.path.join(
#         dossier_enregistrement, nom_fichier_filtre)
#     appliquer_filtres(fichier_sar, chemin_image_filtre)

def isPollutionOnImage(image_path):
    return False


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

    # Bouton pour télécharger les données
    bouton_telecharger = ttk.Button(
        frame_main, text="Télécharger les données", command=telecharger_donnees)
    bouton_telecharger.grid(row=6, column=0, columnspan=3,
                            pady=15, sticky=tk.W+tk.E)

    # Bouton pour traiter une image SAR
    # bouton_traiter_image = ttk.Button(
    #     frame_main, text="Traiter une image SAR", command=traiter_image)
    # bouton_traiter_image.grid(
    #     row=7, column=0, columnspan=3, pady=15, sticky=tk.W+tk.E)

    # Dimensionnement automatique de la fenêtre
    fenetre.update_idletasks()
    # Taille minimale pour éviter des réductions excessives
    fenetre.minsize(800, 600)
    fenetre.mainloop()


def create_aoi_mask(geometry, image_size, bbox):
    """
    Crée un masque pour recadrer l'image selon l'AOI du GeoJSON.
    `geometry`: Géométrie de l'AOI sous forme de polygone.
    `image_size`: Dimensions de l'image (largeur, hauteur).
    `bbox`: Bounding box (BBox) de l'image.
    """
    # Convertir les coordonnées du polygone en coordonnées de pixels
    poly = shape(geometry)
    min_x, min_y, max_x, max_y = bbox

    # Taille de l'image en pixels
    width, height = image_size

    # Créer une image binaire vide
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)

    # Redimensionner le polygone aux dimensions de l'image
    def scale_coords(x, y):
        return ((x - min_x) / (max_x - min_x) * width,
                height - (y - min_y) / (max_y - min_y) * height)

    pixel_coords = [scale_coords(x, y) for x, y in poly.exterior.coords]
    draw.polygon(pixel_coords, fill=1)

    return np.array(mask)


# Lancer l'interface utilisateur
if __name__ == "__main__":
    interface_utilisateur()
