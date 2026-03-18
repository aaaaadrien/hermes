import requests
import unittest

def outil_wiki(sujet: str) -> str:
    url = "https://fr.wikipedia.org/w/api.php"
    
    # Fix sinon bloqué
    headers = {
        'User-Agent': 'Linuxtricks/1.0'
    }
    
    params = {
        "action": "query",
        "prop": "extracts",
        "explaintext": True,
        "titles": sujet,
        "format": "json",
        "redirects": 1
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=5)
        
        # Vérifie si la requête HTTP a réussi (200 OK)
        response.raise_for_status()
        
        res = response.json()
        pages = res.get("query", {}).get("pages", {})
        
        if not pages:
            return f"Aucune page Wikipédia trouvée pour « {sujet} »."
            
        page_id = next(iter(pages))
        page_data = pages[page_id]

        if "missing" in page_data or page_id == "-1":
            return f"Aucune page Wikipédia trouvée pour « {sujet} »."

        return page_data.get("extract", "")

    except requests.exceptions.HTTPError as e:
        return f"⚠️ Erreur HTTP : {e}"
    except Exception as e:
        return f"⚠️ Erreur : {e}"

# --- Script de Test ---

class TestWiki(unittest.TestCase):
    def test_nathalie_koenders(self):
        resultat = outil_wiki("Nathalie Koenders")
        self.assertIsInstance(resultat, str)
        # On vérifie Dijon car elle est première adjointe à la mairie de Dijon
        self.assertIn("Dijon", resultat)
        print(f"\n✅ Succès ! Taille du contenu : {len(resultat)} caractères.")

    def test_page_inexistante(self):
        resultat = outil_wiki("CeciN-EstPasUnePageValide12345")
        self.assertTrue(resultat.startswith("Aucune page Wikipédia trouvée"))
        print("✅ Succès du test d'absence de page.")

if __name__ == "__main__":
    unittest.main()
