import spacy;
nlp = spacy.load('en_core_web_lg')


def run_engine_by_factors():
    pass



def test_nlp ():
    address = "180 Myrtle Ave, Brooklyn, NY 11201, United States"
    doc = nlp(address)

    for ent in doc.ents:
        print(ent.text, ent.label_,ent.orth_,ent.lemma_)
