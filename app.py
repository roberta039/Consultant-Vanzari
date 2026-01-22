import streamlit as st
import google.generativeai as genai
import sqlite3
import uuid
import os
import tempfile
from datetime import datetime
import time

# --- CONFIGURARE PAGINĂ ---
st.set_page_config(page_title="Consultant Vânzări IT AI", layout="wide")

# --- 1. GESTIONARE BAZĂ DE DATE (SQLite) ---
DB_FILE = "chat_history.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (session_id TEXT, role TEXT, content TEXT, timestamp DATETIME)''')
    conn.commit()
    conn.close()

def save_message(session_id, role, content):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO messages VALUES (?, ?, ?, ?)", 
              (session_id, role, content, datetime.now()))
    conn.commit()
    conn.close()

def load_history(session_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY timestamp", (session_id,))
    rows = c.fetchall()
    conn.close()
    # Formatăm pentru Streamlit
    history = []
    for role, content in rows:
        history.append({"role": role, "content": content})
    return history

def clear_session_history(session_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()

# Inițializăm baza de date la pornire
init_db()

# --- 2. GESTIONARE ID SESIUNE (Query Params) ---
# Verificăm dacă există un ID în URL, altfel creăm unul
if "session_id" not in st.query_params:
    new_id = str(uuid.uuid4())
    st.query_params["session_id"] = new_id
    session_id = new_id
else:
    session_id = st.query_params["session_id"]

# --- 3. GESTIONARE CHEI API (Rotație & Fallback) ---
def configure_gemini():
    """
    Încearcă cheile din st.secrets. Dacă una e expirată, trece la următoarea.
    Dacă nu există chei valide, cere utilizatorului una.
    Returnează modelul configurat sau None.
    """
    api_keys = []
    
    # Încercăm să luăm cheile din secrets (formatate ca listă sau string cu virgulă)
    if "api_keys" in st.secrets:
        if isinstance(st.secrets["api_keys"], list):
            api_keys = st.secrets["api_keys"]
        else:
            api_keys = st.secrets["api_keys"].split(",")
    
    valid_model = None
    working_key = None

    # Iterăm prin cheile definite în secrets
    for key in api_keys:
        key = key.strip()
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel('gemini-1.5-flash')
            # Test rapid pentru a vedea dacă cheia e activă
            response = model.generate_content("test", request_options={"timeout": 5})
            working_key = key
            valid_model = model
            break # Am găsit o cheie bună
        except Exception as e:
            st.sidebar.error(f"Cheia care se termină în ...{key[-4:]} a expirat sau e invalidă.")
            continue

    # Dacă nu am găsit nicio cheie validă în secrets, cerem în UI
    if not valid_model:
        st.sidebar.warning("Nicio cheie API din sistem nu funcționează.")
        user_key = st.sidebar.text_input("Introdu o cheie API Google Gemini validă:", type="password")
        if user_key:
            try:
                genai.configure(api_key=user_key)
                model = genai.GenerativeModel('gemini-1.5-flash')
                model.generate_content("test")
                valid_model = model
                st.sidebar.success("Cheie utilizator validată!")
            except Exception as e:
                st.sidebar.error("Cheia introdusă nu este validă.")
    
    return valid_model

# --- 4. FUNCȚII UPLOAD FIȘIERE ---
def upload_to_gemini(uploaded_file):
    """Încarcă fișierul temporar și îl trimite la Google Gemini"""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name

        # Upload către Gemini
        gemini_file = genai.upload_file(path=tmp_path, display_name=uploaded_file.name)
        
        # Așteptăm procesarea (doar dacă e necesar, de obicei pt video/audio mari, dar bun ca practică)
        while gemini_file.state.name == "PROCESSING":
            time.sleep(1)
            gemini_file = genai.get_file(gemini_file.name)
            
        os.remove(tmp_path) # Ștergem local
        return gemini_file
    except Exception as e:
        st.error(f"Eroare la upload: {e}")
        return None

# --- INTERFAȚA GRAFICĂ (UI) ---

st.title("🤖 Asistent Vânzări IT - AI")
st.markdown(f"**ID Sesiune:** `{session_id}` (Poți reveni pe acest link pentru a continua discuția)")

# Configurare Model
model = configure_gemini()

# Sidebar
with st.sidebar:
    st.header("📂 Documente Companie")
    st.info("Încarcă documentele pentru a oferi context AI-ului.")
    
    portfolio_file = st.file_uploader("Portofoliu Companie (PDF)", type=['pdf'])
    catalog_file = st.file_uploader("Catalog Produse & Prețuri (PDF/TXT/CSV)", type=['pdf', 'txt', 'csv'])
    
    files_context = []
    
    if st.button("Procesează Documentele"):
        if model:
            with st.spinner("Se încarcă fișierele pe serverele Google..."):
                if portfolio_file:
                    f1 = upload_to_gemini(portfolio_file)
                    if f1: 
                        st.session_state['portfolio_ref'] = f1
                        st.success("Portofoliu încărcat!")
                
                if catalog_file:
                    f2 = upload_to_gemini(catalog_file)
                    if f2: 
                        st.session_state['catalog_ref'] = f2
                        st.success("Catalog încărcat!")
        else:
            st.error("Modelul AI nu este configurat. Verifică cheile API.")

    st.divider()
    if st.button("RESET CONVERSAȚIE", type="primary"):
        clear_session_history(session_id)
        st.rerun()

# Recuperare istoric din SQLite
if "messages" not in st.session_state:
    st.session_state.messages = load_history(session_id)

# Afișare chat
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Zona de input
if prompt := st.chat_input("Ex: Clientul vrea o ofertă pentru 10 laptopuri și server de stocare..."):
    if not model:
        st.error("Te rog configurează o cheie API validă în sidebar.")
    else:
        # 1. Adăugăm mesajul utilizatorului în UI și DB
        st.session_state.messages.append({"role": "user", "content": prompt})
        save_message(session_id, "user", prompt)
        with st.chat_message("user"):
            st.markdown(prompt)

        # 2. Pregătim contextul pentru AI
        conversation_context = []
        
        # Instrucțiuni de sistem
        system_instruction = """
        Ești un agent expert în vânzări IT. 
        Rolul tău este să analizezi cerințele clientului și să propui soluții folosind DOAR echipamentele și serviciile din fișierele încărcate (dacă există).
        Dacă utilizatorul cere o ofertă, genereaz-o într-un format clar, tabelar, cu prețuri (dacă sunt disponibile în catalog).
        Fii politicos, profesionist și orientat spre vânzare.
        """
        
        # Adăugăm fișierele încărcate în request (dacă există în sesiune)
        current_request = [system_instruction]
        
        if 'portfolio_ref' in st.session_state:
            current_request.append("Acesta este portofoliul companiei:")
            current_request.append(st.session_state['portfolio_ref'])
            
        if 'catalog_ref' in st.session_state:
            current_request.append("Acesta este catalogul de produse și prețuri:")
            current_request.append(st.session_state['catalog_ref'])
            
        # Adăugăm istoricul conversației (pentru context conversațional)
        # Nota: Gemini API 1.5 suportă istoric mare, dar aici simplificăm trimițând promptul curent + fișierele.
        # Pentru chat history complet cu fișiere, se folosește start_chat, dar e complex cu fișierele stateless.
        # O abordare hibridă: trimitem istoricul recent text + fișierele la fiecare call (stateless approach).
        
        history_text = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in st.session_state.messages[-5:]]) # Ultimele 5 mesaje context
        current_request.append(f"Istoric recent discuție:\n{history_text}")
        current_request.append(f"SOLICITARE CURENTĂ: {prompt}")

        # 3. Generăm răspunsul
        with st.chat_message("assistant"):
            with st.spinner("AI-ul analizează cererea și portofoliul..."):
                try:
                    response = model.generate_content(current_request)
                    response_text = response.text
                    
                    st.markdown(response_text)
                    
                    # Salvare în DB și Sesiune
                    st.session_state.messages.append({"role": "assistant", "content": response_text})
                    save_message(session_id, "assistant", response_text)

                    # Buton descărcare ofertă
                    st.download_button(
                        label="📥 Descarcă Răspunsul / Oferta (TXT)",
                        data=response_text,
                        file_name=f"oferta_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                        mime="text/plain"
                    )

                except Exception as e:
                    st.error(f"A apărut o eroare la generare: {e}")
