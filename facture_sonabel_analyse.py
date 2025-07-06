# Module 1 : OCR + Correction intelligente des index SONABEL
import pytesseract
import fitz  # PyMuPDF (ensure it's installed via "pip install pymupdf")
from PIL import Image, ImageDraw
import re
import io
import cv2
import numpy as np
import streamlit as st
import pandas as pd
import tempfile
from fpdf import FPDF

def preprocess_image(img_pil):
    img = np.array(img_pil.convert('L'))  # Conversion en niveaux de gris
    _, thresh = cv2.threshold(img, 150, 255, cv2.THRESH_BINARY)
    return Image.fromarray(thresh)

def extraire_index_depuis_pdf(pdf_path):
    doc = fitz.open(stream=pdf_path.read(), filetype="pdf")
    index_data = []

    for page in doc:
        pix = page.get_pixmap(dpi=300)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        img_preprocessed = preprocess_image(img)

        text1 = pytesseract.image_to_string(img_preprocessed, config='--psm 6')
        text2 = pytesseract.image_to_string(img_preprocessed, config='--psm 11')

        raw_text = text1 + "\n" + text2
        matches = re.findall(r"(\d{5,6})", raw_text)
        index_data.extend(matches)

    index_corriges = [corriger_erreurs_ocr(val) for val in index_data]
    index_valides = [int(i) for i in index_corriges if i.isdigit() and 10000 < int(i) < 999999]
    return sorted(index_valides)

def extraire_index_depuis_image(image_file):
    img = Image.open(image_file)
    img_preprocessed = preprocess_image(img)

    img_for_boxes = img.convert("RGB")
    draw = ImageDraw.Draw(img_for_boxes)

    data = pytesseract.image_to_data(img_preprocessed, config='--psm 6', output_type=pytesseract.Output.DICT)
    matches = []
    for i, word in enumerate(data['text']):
        if re.fullmatch(r"\d{5,6}", word):
            x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
            draw.rectangle([x, y, x + w, y + h], outline="red", width=2)
            matches.append(word)

    index_corriges = [corriger_erreurs_ocr(val) for val in matches]
    index_valides = [int(i) for i in index_corriges if i.isdigit() and 10000 < int(i) < 999999]

    st.image(img_for_boxes, caption="Index détectés (zones surlignées)", use_column_width=True)
    return sorted(index_valides)

def corriger_erreurs_ocr(val):
    erreurs_ocr = {'O': '0', 'I': '1', 'S': '5', 'B': '8', 'Z': '2', 'l': '1'}
    for k, v in erreurs_ocr.items():
        val = val.replace(k, v)
    return val

def generer_tableur_index(data, tarifs=None, montants_factures=None):
    df = pd.DataFrame(data, columns=["Mois", "Ancien", "Nouveau"])
    df["kWh"] = df["Nouveau"] - df["Ancien"]
    df["Écart %"] = df["kWh"].pct_change().fillna(0).apply(lambda x: round(x*100, 2))
    df["Alerte"] = df["Écart %"].apply(lambda x: "⚠️" if abs(x) > 50 else "")

    if tarifs:
        df["Montant Énergie"] = df["kWh"].apply(lambda x: round(calcul_montant_theorique(x, tarifs), 2))
        df["Frais Fixes"] = tarifs["prime"] + tarifs["location"]
        df["Montant HT"] = df["Montant Énergie"] + df["Frais Fixes"]
        df["TVA"] = df["Montant HT"] * 0.18
        df["Montant Théorique"] = df["Montant HT"] + df["TVA"]

    if montants_factures:
        df["Montant Facturé"] = montants_factures
        df["Écart FCFA"] = df["Montant Facturé"] - df["Montant Théorique"]
        df["Alerte Tarifs"] = df["Montant Facturé"] > df["Montant Théorique"] * 1.25

    return df

def calcul_montant_theorique(kwh, tarifs):
    total = 0
    if kwh <= 75:
        total = kwh * tarifs["t1"]
    elif kwh <= 150:
        total = 75 * tarifs["t1"] + (kwh - 75) * tarifs["t2"]
    else:
        total = 75 * tarifs["t1"] + 75 * tarifs["t2"] + (kwh - 150) * tarifs["t3"]
    return total

def exporter_excel(df):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        df.to_excel(tmp.name, index=False)
        return tmp.name

def exporter_pdf(df):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="Rapport de consommation SONABEL", ln=True, align='C')
    pdf.ln(10)
    for i, row in df.iterrows():
        ligne = f"{row['Mois']} | Ancien: {row['Ancien']} | Nouveau: {row['Nouveau']} | kWh: {row['kWh']} | Ecart: {row['Écart %']}% {row['Alerte']}"
        if "Montant Théorique" in row:
            ligne += f" | Théorique: {row['Montant Théorique']:.0f}"
        if "Montant Facturé" in row:
            ligne += f" | Facturé: {row['Montant Facturé']} | Écart: {row['Écart FCFA']:.0f}"
            if row.get("Alerte Tarifs"):
                ligne += " ⚠️ Dépassement"
        pdf.cell(200, 10, txt=ligne, ln=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        pdf.output(tmp.name)
        return tmp.name

def interface_streamlit():
    st.title("Analyse des Factures SONABEL")

    uploaded_pdf = st.file_uploader("Importer une facture (PDF)", type="pdf")
    uploaded_img = st.file_uploader("Ou importer une image (JPG/PNG)", type=["jpg", "jpeg", "png"])

    index_detectes = []
    if uploaded_pdf:
        try:
            index_detectes = extraire_index_depuis_pdf(uploaded_pdf)
        except Exception as e:
            st.error(f"Erreur PDF : {e}")
    elif uploaded_img:
        try:
            index_detectes = extraire_index_depuis_image(uploaded_img)
        except Exception as e:
            st.error(f"Erreur Image : {e}")

    if index_detectes:
        st.write("Index détectés :", index_detectes)

    manuel_ancien = st.checkbox("Saisir manuellement l'index ancien")
    if manuel_ancien:
        ancien = st.number_input("Ancien index (manuel)", min_value=0)
    else:
        ancien = st.number_input("Ancien index", value=int(index_detectes[0]) if len(index_detectes) > 0 else 0)

    manuel_nouveau = st.checkbox("Saisir manuellement l'index nouveau")
    if manuel_nouveau:
        nouveau = st.number_input("Nouveau index (manuel)", min_value=0)
    else:
        nouveau = st.number_input("Nouveau index", value=int(index_detectes[1]) if len(index_detectes) > 1 else 0)

    consommation = nouveau - ancien
    st.metric("Consommation (kWh)", consommation)

    if consommation < 0:
        st.error("Index incohérents !")
    elif consommation > 500:
        st.warning("Consommation élevée !")
    else:
        st.success("Consommation normale")

    st.write("\n---\n")
    st.write("**Historique mensuel avec calculs**")

    tarifs = {"t1": 94, "t2": 130, "t3": 159, "prime": 471, "location": 1914}
    montants = [17321, 19141, 25791]

    historique = generer_tableur_index([
        ("Déc 2023", 39000, 39200),
        ("Jan 2024", 39200, 39500),
        ("Fév 2025", ancien, nouveau)
    ], tarifs=tarifs, montants_factures=montants)

    st.dataframe(historique)

    if st.button("📥 Exporter en Excel"):
        path = exporter_excel(historique)
        with open(path, "rb") as f:
            st.download_button("Télécharger le fichier Excel", f, file_name="rapport_sonabel.xlsx")

    if st.button("📄 Exporter en PDF"):
        path = exporter_pdf(historique)
        with open(path, "rb") as f:
            st.download_button("Télécharger le fichier PDF", f, file_name="rapport_sonabel.pdf")

# Pour lancer l'interface :
# streamlit run ce_script.py
