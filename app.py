"""Sujet 9 - Analyse de données sismiques (USGS) : interface Streamlit.
Lancer :  streamlit run app.py
"""
import os
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Séismes USGS - Sujet 9", page_icon="🌍", layout="wide")

CSV_PATH = os.environ.get("CSV_PATH", "data/query.csv")
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
CATS = ["Faible (<4.5)", "Modérée (4.5-5.4)", "Forte (5.5-6.4)", "Majeure (≥6.5)"]


def categorize(m):
    if m < 4.5:
        return CATS[0]
    if m < 5.5:
        return CATS[1]
    if m < 6.5:
        return CATS[2]
    return CATS[3]


@st.cache_data(show_spinner="Chargement du CSV...")
def load(path_or_file):
    df = pd.read_csv(path_or_file)
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_localize(None)  # timestamp
    df = df.dropna(subset=["time", "latitude", "longitude", "mag", "place"]).copy()
    df["categorie"] = df["mag"].apply(categorize)
    df["mois"] = df["time"].dt.to_period("M").astype(str)
    df["heure"] = df["time"].dt.hour
    df["zone_texte"] = df["place"].str.split(",").str[-1].str.strip()  # texte libre, pas une région normalisée
    return df


# ---------- Source des données ----------
st.sidebar.title("🌍 Séismes USGS")
up = st.sidebar.file_uploader("Autre CSV USGS (optionnel)", type="csv")
try:
    data = load(up if up else CSV_PATH)
except Exception as e:
    st.error(f"Impossible de lire le CSV : {e}")
    st.stop()

# ---------- Filtres ----------
st.sidebar.header("Filtres")
dmin, dmax = data["time"].min().date(), data["time"].max().date()
dates = st.sidebar.date_input("Période", (dmin, dmax), min_value=dmin, max_value=dmax)
if isinstance(dates, tuple) and len(dates) == 2:
    d1, d2 = dates
else:
    d1 = d2 = dates[0] if isinstance(dates, tuple) else dates
mag = st.sidebar.slider("Magnitude", float(data.mag.min()), float(data.mag.max()),
                        (float(data.mag.min()), float(data.mag.max())), 0.1)
cats = st.sidebar.multiselect("Catégorie de magnitude", CATS, default=CATS)
types = st.sidebar.multiselect("Type d'événement", sorted(data["type"].unique()),
                               default=sorted(data["type"].unique()))
txt = st.sidebar.text_input("Texte dans la localisation (champ place)", placeholder="ex : Japan, Chile...")
depth = st.sidebar.slider("Profondeur (km)", float(data.depth.min()), float(data.depth.max()),
                          (float(data.depth.min()), float(data.depth.max())))

f = data[(data.time.dt.date >= d1) & (data.time.dt.date <= d2)
         & data.mag.between(*mag) & data.categorie.isin(cats) & data["type"].isin(types)
         & data.depth.between(*depth)]
if txt:
    f = f[f.place.str.contains(txt, case=False, na=False, regex=False)]

st.title("Analyse de données sismiques")
st.caption(f"Source : catalogue USGS · fichier : {up.name if up else CSV_PATH} · "
           f"{len(data):,} événements valides chargés")
if f.empty:
    st.warning("Aucun événement ne correspond aux filtres.")
    st.stop()

tabs = st.tabs(["📊 Vue d'ensemble", "📅 Temps", "🗺️ Carte", "📍 Localisations",
                "⚡ Spark SQL", "🍃 MongoDB", "📄 Données"])

# ---------- Vue d'ensemble ----------
with tabs[0]:
    c = st.columns(5)
    c[0].metric("Événements", f"{len(f):,}")
    c[1].metric("Magnitude moyenne", f"{f.mag.mean():.2f}")
    c[2].metric("Magnitude max", f"{f.mag.max():.1f}")
    c[3].metric("Profondeur moyenne", f"{f.depth.mean():.0f} km")
    c[4].metric("Événements ≥ 6", f"{(f.mag >= 6).sum():,}")
    a, b = st.columns(2)
    a.plotly_chart(px.histogram(f, x="mag", nbins=40, title="Distribution des magnitudes",
                                labels={"mag": "Magnitude"}), use_container_width=True)
    cc = f.categorie.value_counts().reindex(CATS).fillna(0).reset_index()
    cc.columns = ["categorie", "n"]
    b.plotly_chart(px.pie(cc, names="categorie", values="n", hole=.4,
                          title="Répartition par catégorie"), use_container_width=True)
    st.plotly_chart(px.scatter(f, x="mag", y="depth", color="categorie", opacity=.5,
                               title="Magnitude vs profondeur", labels={"depth": "Profondeur (km)", "mag": "Magnitude"})
                    .update_yaxes(autorange="reversed"), use_container_width=True)

# ---------- Temps ----------
with tabs[1]:
    m = f.groupby(["mois", "categorie"]).size().reset_index(name="n")
    st.plotly_chart(px.bar(m, x="mois", y="n", color="categorie", title="Événements par mois et par catégorie",
                           category_orders={"categorie": CATS}, labels={"n": "Nombre", "mois": "Mois"}),
                    use_container_width=True)
    jour = f.groupby(f.time.dt.date).size().reset_index(name="n")
    jour.columns = ["jour", "n"]
    st.plotly_chart(px.line(jour, x="jour", y="n", title="Événements par jour"), use_container_width=True)
    h = f.groupby("heure").size().reset_index(name="n")
    st.plotly_chart(px.bar(h, x="heure", y="n", title="Événements par heure (UTC)"), use_container_width=True)
    st.subheader("Tableau mois × catégorie")
    st.dataframe(m.pivot(index="mois", columns="categorie", values="n").fillna(0).astype(int)
                 .reindex(columns=[c for c in CATS if c in m.categorie.unique()]), use_container_width=True)

# ---------- Carte ----------
with tabs[2]:
    n = st.slider("Nombre max de points affichés", 500, 10000, 3000, 500)
    s = f.sample(min(n, len(f)), random_state=1)
    fig = px.scatter_geo(s, lat="latitude", lon="longitude", color="mag", size=(s.mag - 3).clip(lower=.5),
                         hover_name="place", hover_data={"time": True, "mag": True, "depth": True},
                         color_continuous_scale="YlOrRd", projection="natural earth",
                         title=f"{len(s):,} séismes")
    fig.update_layout(height=600, margin=dict(l=0, r=0, t=40, b=0))
    st.plotly_chart(fig, use_container_width=True)
    st.subheader("Top 10 des plus forts séismes")
    st.dataframe(f.nlargest(10, "mag")[["time", "mag", "depth", "place"]], use_container_width=True)

# ---------- Localisations ----------
with tabs[3]:
    st.info("⚠️ Le champ `place` est une **description textuelle** (ville la plus proche), "
            "pas une région administrative normalisée. La « zone » ci-dessous est simplement le dernier "
            "segment du texte (souvent un pays ou un état) : à interpréter avec prudence.")
    k = st.slider("Nombre de zones", 5, 30, 15)
    z = (f.groupby("zone_texte").agg(n=("mag", "size"), mag_moy=("mag", "mean"), mag_max=("mag", "max"))
         .sort_values("n", ascending=False).head(k).reset_index())
    st.plotly_chart(px.bar(z, x="n", y="zone_texte", orientation="h", title="Zones les plus fréquentes",
                           labels={"n": "Événements", "zone_texte": ""}).update_yaxes(autorange="reversed"),
                    use_container_width=True)
    st.dataframe(z.round(2), use_container_width=True)

# ---------- Spark SQL ----------
with tabs[4]:
    st.write("Exécute des requêtes **Spark SQL** sur la vue `seismes` (données filtrées). "
             "Nécessite `pyspark` et Java.")
    PRESETS = {
        "Événements par mois": "SELECT mois, COUNT(*) AS n FROM seismes GROUP BY mois ORDER BY mois",
        "Par catégorie": "SELECT categorie, COUNT(*) AS n, ROUND(AVG(depth),1) AS prof_moy FROM seismes GROUP BY categorie ORDER BY n DESC",
        "Top 10 magnitudes": "SELECT time, mag, place FROM seismes ORDER BY mag DESC LIMIT 10",
        "Top zones (texte)": "SELECT zone_texte, COUNT(*) AS n FROM seismes GROUP BY zone_texte ORDER BY n DESC LIMIT 10",
        "Par heure": "SELECT heure, COUNT(*) AS n FROM seismes GROUP BY heure ORDER BY heure",
        "Profonds (>300 km) et mag ≥ 5": "SELECT time, mag, depth, place FROM seismes WHERE depth > 300 AND mag >= 5 ORDER BY mag DESC",
    }
    ch = st.selectbox("Requête prédéfinie", list(PRESETS))
    q = st.text_area("Requête SQL", PRESETS[ch], height=100)
    if st.button("Exécuter avec Spark"):
        try:
            from pyspark.sql import SparkSession
            spark = SparkSession.builder.master("local[*]").appName("seismes").getOrCreate()
            sdf = spark.createDataFrame(f.assign(time=f.time.astype(str)).drop(columns=["updated"]))
            sdf.createOrReplaceTempView("seismes")
            res = spark.sql(q).toPandas()
            st.dataframe(res, use_container_width=True)
        except ImportError:
            st.error("pyspark n'est pas installé : `pip install pyspark` (+ Java).")
        except Exception as e:
            st.error(e)

# ---------- MongoDB ----------
with tabs[5]:
    uri = st.text_input("URI MongoDB", MONGO_URI)
    dbn, coln = st.columns(2)
    db_name = dbn.text_input("Base", "mini_projet")
    col_name = coln.text_input("Collection", "seismes")
    try:
        import pymongo
        client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=2500)
        client.admin.command("ping")
        col = client[db_name][col_name]
        st.success(f"Connecté · {col.count_documents({}):,} documents dans {db_name}.{col_name}")
    except ImportError:
        st.error("pymongo non installé : `pip install pymongo`")
        col = None
    except Exception as e:
        st.warning(f"MongoDB inaccessible ({e}). Lancez : docker run -d --name mongo-mini -p 27017:27017 mongo:7")
        col = None

    if col is not None:
        b1, b2 = st.columns(2)
        if b1.button(f"📥 Importer les {len(f):,} événements filtrés"):
            docs = f.drop(columns=["updated"]).to_dict("records")
            for d in docs:
                d["time"] = d["time"].to_pydatetime()
            col.drop()
            col.insert_many(docs)
            col.create_index("mag")
            col.create_index("time")
            st.success(f"{len(docs):,} documents importés.")
        if b2.button("🗑️ Vider la collection"):
            col.drop()
            st.info("Collection supprimée.")

        st.subheader("Recherche")
        r1, r2, r3, r4 = st.columns(4)
        mmin = r1.number_input("Magnitude min", 0.0, 10.0, 6.0, 0.1)
        place_q = r2.text_input("Place contient", "")
        ds = r3.date_input("Depuis", dmin)
        de = r4.date_input("Jusqu'à", dmax)
        import datetime as dt
        flt = {"mag": {"$gte": mmin},
               "time": {"$gte": dt.datetime.combine(ds, dt.time.min), "$lte": dt.datetime.combine(de, dt.time.max)}}
        if place_q:
            flt["place"] = {"$regex": place_q, "$options": "i"}
        st.code(f"db.{col_name}.find({flt}).sort({{mag:-1}}).limit(50)", language="javascript")
        res = list(col.find(flt, {"_id": 0, "time": 1, "mag": 1, "depth": 1, "place": 1}).sort("mag", -1).limit(50))
        st.dataframe(pd.DataFrame(res), use_container_width=True)

        st.subheader("Agrégation : nombre et magnitude moyenne par catégorie")
        pipe = [{"$group": {"_id": "$categorie", "n": {"$sum": 1}, "mag_moy": {"$avg": "$mag"}}},
                {"$sort": {"n": -1}}]
        st.code(f"db.{col_name}.aggregate({pipe})", language="javascript")
        st.dataframe(pd.DataFrame(list(col.aggregate(pipe))), use_container_width=True)

# ---------- Données ----------
with tabs[6]:
    cols = ["time", "latitude", "longitude", "depth", "mag", "categorie", "place", "type", "id"]
    st.dataframe(f[cols].sort_values("time", ascending=False), use_container_width=True, height=500)
    x1, x2 = st.columns(2)
    x1.download_button("⬇️ CSV", f[cols].to_csv(index=False).encode(), "seismes_filtres.csv", "text/csv")
    x2.download_button("⬇️ JSON (import mongoimport --jsonArray)",
                       f[cols].assign(time=f.time.astype(str)).to_json(orient="records").encode(),
                       "seismes_filtres.json", "application/json")
