# Roadmap restante verso Sudoku Logic Lab 1.0

## Perimetro della versione 1.0

La versione 1.0 deve essere un solver logico avanzato per Sudoku classico 9×9 con:

* tassonomia stabile e coerente;
* identificatori permanenti per tutte le tecniche;
* classificazione strutturale delle mosse;
* tecniche locali, fish, coloring, unicità, catene, ALS e forcing avanzati;
* vere Nested Forcing Chains;
* Complete Forcing Tree come ultimo fallback;
* prove serializzabili e verificabili;
* scala SE e pseudo-SE trasparente.

Non è necessario includere ogni nome mai inventato nella comunità Sudoku. La copertura della 1.0 deve corrispondere alle principali tecniche documentate da Sudoku Explainer, SukakuExplainer e HoDoKu, con le famiglie parametriche rappresentate da motori generali.

## Baseline acquisito

Le patch P01-P16, inclusa P06.5, sono applicate e non fanno più parte della roadmap operativa. Il progetto dispone già di:

* catalogo centrale e identificatori stabili;
* `TASSIONOMIA.md` come fonte normativa e catalogo come sua proiezione
  eseguibile P16;
* separazione fra `inference_engine` semantico ed `engine_type` esecutivo;
* registro dichiarativo dei detector;
* pipeline ordinary, Nested e Complete Tree separata;
* `ProofDAG` autorevole e viste lineari derivate;
* metriche condivise, descrizioni e highlight normalizzati;
* contratto di presentazione candidate-level: spiegazioni a sezioni,
  `visual_evidence` con ruoli semantici, snapshot candidati prima/dopo,
  renderer testuale pencil-mark e player web coerente;
* P09.6 di presentazione: distinzione tra celle implicanti e celle modificate,
  palette semantica, controlli stabili, candidati leggibili su telefono e
  overlay SVG riservato alle inferenze esplicite del `ProofDAG`;
* archi ordinati con motivo e forza `strong`/`weak`;
* classificazione strutturale delle catene esistenti;
* contesto di unicità verificato, givens distinti dalle celle risolte e famiglia Unique Loop strutturale;
* Sue de Coq classica ed estesa, Aligned Pair/Triplet Exclusion e subset generalizzati fino al Sextuple;
* motore Fish parametrico per X-Wing, Swordfish e Jellyfish Basic, Franken e Mutant,
  con varianti Finned, Sashimi, Siamese, Endo-Finned e Cannibalistic;
* Coloring sul grafo condiviso delle conjugate pair, con componenti bipartite,
  Color Trap, Color Wrap e Multi Colors Type 1/2;
* grafo AIC completo con supporti autorevoli degli archi nel `ProofDAG`,
  X-Chain, XY-Chain, Discontinuous Nice Loop, AIC Type 1/2 e Continuous Nice
  Loop classificati da alternanza, chiusura ed endpoint;
* `GroupNode` come proposizione OR confinata in un segmento linea-box,
  visibilità whole-set, strong link come partizione esatta di casa e un unico
  grafo candidato/gruppo per Grouped X-Chain, Grouped AIC, Grouped Nice Loop e
  Grouped Continuous Nice Loop;
* motore ALS comune con enumerazione deduplicata, grafo RCC a visibilità
  completa, overlap validati, ALS-XZ, ALS-XY-Wing, ALS Chain, Death Blossom e
  ALS-AIC reale con nodi ALS tipizzati; WXYZ/VWXYZ/UVWXYZ/TUVWXYZ-Wing sono
  classificazioni del parent ALS e non detector paralleli;
* precedenza strutturale ALS/Grouped sulla forma chain/net fuori dal forcing
  context, senza riclassificare le normali XY-Chain come ALS-AIC;
* metriche specifiche `group_node_count`, `max_group_size`, `als_node_count`,
  `als_cell_count` e `rcc_count`;
* classificazione P15 chain/net dal DAG e metriche di fork, merge e parent;
* Templates per singola cifra e Kraken Fish Type 1/2 sopra Fish e grafo AIC;
* vere Nested Forcing Chains con sottoprove di inferenze interne, memoizzazione,
  cycle guard e budget depth 1-2;
* versionamento esplicito di prove e analisi archiviate.

Le patch future devono estendere queste strutture, non crearne copie parallele.

## P14.1. Unificazione tassonomia/codice — completata

Contratto acquisito:

* ID moderni e migrazione degli ID legacy per Direct Hidden subset, Sue de Coq
  e Aligned Triplet Exclusion;
* nome canonico `XY-Wing`, con `Y-Wing` conservato come alias;
* `ALSNode` serializzabile con semantica OR per cifra e ALS multicella
  obbligatorio nelle ALS-AIC;
* ALS-AIC ricercata nel grafo misto candidate/ALS con link `als-strong`,
  `als-weak` e `als-rcc`;
* persistenza del motore semantico e versioni prova `3.4.0` / metriche `3.1.0`;
* budget ordinario ALS-AIC: 64 ALS, 256 endpoint, 2048 stati per percorso.

La taratura di rating, soglie e carico risolutivo resta deliberatamente P18.

---

# Blocco E: forcing avanzato

## P15. Classificazione dei Proof DAG non lineari e Forcing Net — completata

### Obiettivo

Usare la non linearità già supportata da `ProofDAG` per distinguere formalmente una catena da una rete di implicazioni.

### Regola

```python
def classify_dependency_shape(proof):
    if any(len(node.parents) > 1 for node in proof.nodes.values()):
        return "net"

    if proof_has_fork_and_merge(proof):
        return "net"

    return "chain"
```

### Tecniche

```text
Contradiction Forcing Net
Double Forcing Net
Cell Forcing Net
Region Forcing Net
Templates
Kraken Fish Type 1
Kraken Fish Type 2
```

### Templates

Devono enumerare configurazioni valide di una singola cifra compatibili con lo stato, non soluzioni complete del puzzle.

### Kraken Fish

Devono combinare:

```text
fish incompleto o finned
insieme delle possibilità rilevanti
catena o net da ogni possibilità
conclusione comune
```

### Criteri di completamento

* Una net non viene mai chiamata chain.
* Templates opera per cifra.
* Kraken conserva sia la struttura fish sia le sottoprove.
* Tutte le fins o possibilità richieste implicano realmente il target.
* Le prove restano finite e spiegabili.

Contratto acquisito: `ProofDAG` è la fonte della forma chain/net; le viste
lineari restano derivate. Templates non emette conclusioni dopo un
troncamento. Kraken conserva il `FishPattern`, tutte le possibilità richieste,
i percorsi AIC e i supporti degli archi.

---

## P16. Vere Nested Forcing Chains — completata

### Obiettivo

Implementare Nested come catene che utilizzano sottocatene per dimostrare singole inferenze interne.

### Semantica

Una prova Nested deve contenere almeno una sottoprova che dimostra un’inferenza usata dalla catena principale.

Non deve:

```text
risolvere tutto il puzzle
esplorare arbitrariamente ogni cella residua
dimostrare soltanto che un ramo completo è insoddisfacibile
```

### Motore

```python
class NestedForcingEngine:
    def prove(
        self,
        state,
        assumptions,
        target,
        *,
        remaining_depth,
        budget,
    ) -> ProofDAG | None:
        ...
```

### Tecniche

```text
Nested Contradiction Forcing Chain
Nested Double Forcing Chain
Nested Cell Forcing Chain
Nested Region Forcing Chain
```

### Requisiti formali

```python
metrics["nested_depth"] >= 1
metrics["nested_subproof_count"] >= 1
```

Altrimenti la tecnica deve essere riclassificata come Dynamic, Plus, Multiple Forcing o Forcing Net.

### Budget iniziale

```python
MAX_NESTED_DEPTH = 2
MAX_NESTED_PROOF_NODES = 512
MAX_NESTED_BRANCHES = 64
MAX_NESTED_SUBPROOFS = 32
MAX_NESTED_RESULTS = 2
```

Questi budget limitano il motore Nested e devono essere esposti chiaramente; non si applicano al Complete Forcing Tree autorevole.

### Memoizzazione

Chiave minima:

```python
(
    state_fingerprint,
    assumptions,
    target,
    remaining_depth,
    rule_profile_id,
)
```

Serve anche un cycle guard per evitare sottoprove ricorsive autoreferenziali.

### Criteri di completamento

* Ogni Nested contiene una sottoprova reale.
* La sottoprova dimostra una singola inferenza della prova contenitore.
* Il motore non prosegue fino alla soluzione completa.
* Complete Forcing Tree resta un motore separato.
* La profondità e il numero di sottoprove vengono conservati correttamente.

Contratto acquisito: una mossa Nested contiene almeno un nodo
`nested-subproof` la cui sottoprova conclude esattamente l'inferenza interna
usata dalla catena principale. Sono implementati e classificati separatamente
i casi Contradiction, Double, Cell e Region. Il motore usa i budget P16,
memoizza su stato/ipotesi/target/profondità/profilo, applica un cycle guard e
non invoca né inizializza il Complete Forcing Tree.

---

## P17. Profili Dynamic, Plus e Nested

### Obiettivo

Rendere esplicito quali regole possano essere utilizzate all'interno di una propagazione (`InferenceProfile`), separando questo concetto da **cosa** viene cercato a ogni stato (`SearchPolicy`) e da **quanto** ciascun detector può costare (`SearchLimits`). I tre assi restano distinti per non trasformare P17 in un unico oggetto ingestibile:

```text
SearchPolicy      quali tecniche cercare nello stato corrente
InferenceProfile  quali regole sono ammesse dentro una chain/dynamic/nested
SearchLimits      quanto può spendere ciascun detector
```

### Regola fondamentale: la mossa minima è indipendente dalla modalità

La prossima mossa applicata deve sempre essere la più semplice disponibile secondo la difficoltà pseudo-SE ("Mio"). Questo non dipende da quale `SearchPolicy` è attiva:

1. si trova e si certifica la difficoltà minima `d_min` dello stato;
2. si decide, in base alla `SearchPolicy`, quante altre mosse dello stato raccogliere attorno a essa;
3. si applica deterministicamente una delle mosse minime.

Le cinque modalità di `SearchPolicy` (sotto) non cambiano mai la mossa scelta: cambiano soltanto quante alternative vengono raccolte.

Una mossa minima è **certificata** solo se ogni detector potenzialmente più semplice ha risposto in modo definitivo con uno di:

```text
FOUND        mossa trovata
EXHAUSTED    nessuna mossa in questo stato per questa tecnica
TRUNCATED    ricerca interrotta da un SearchLimits, esito indeterminato
```

Se un detector più semplice risponde `TRUNCATED`, la mossa trovata dopo di esso è soltanto la **minima conosciuta**, non necessariamente la minima reale: questa distinzione deve essere rappresentata nei risultati (es. `certified: bool`), non silenziata.

### Scalini di ricerca (`search_tier`)

`SearchPolicy` opera su uno scalino esplicito, `search_tier`, distinto da `family_id`/`strategy_id`/`inference_engine`: raggruppa le tecniche come le cercherebbe un umano, non come sono implementate. Contratto e tabella completa in `TASSIONOMIA.md`, sezione "Scalini di ricerca P17"; proiezione eseguibile in `technique_catalog.TECHNIQUE_SEARCH_TIER` / `SEARCH_TIER_NAMES_IT`.

```text
0  Elementari              singles, direct, locked candidates, subset
1  Pattern a cifra singola fish, Skyscraper, 2-String Kite, Empty Rectangle
2  Pattern multi-cifra     wings, uniqueness locale, Sue de Coq, ALS locali
3  Catene statiche         X-Chain, XY-Chain, AIC, Nice Loop, ALS-chain
4  Forcing avanzato        multiple/dynamic/plus, forcing net, templates, Kraken
5  Nested forcing          vere Nested Chain con sottoprove
6  Esaustivo               Complete Forcing Tree
```

Lo scalino non segue il numero di cifre coinvolte ma la famiglia cognitiva: una X-Chain resta in "Catene statiche" anche se usa una sola cifra; Swordfish e i fish finned restano "Pattern a cifra singola" anche se difficili; Kraken Fish appartiene al "Forcing avanzato" perché il fish è solo il guscio esterno e la dimostrazione vera passa per le catene.

### Le cinque `SearchPolicy`

```text
superficial     soltanto le mosse con difficoltà minima effettiva
smart_profile   default. Scalino della mossa minima + finestra p dentro quello scalino soltanto
full_profile    finestra p su tutte le tecniche, senza vincolo di scalino (comportamento "profile" attuale)
smart_deep      scalino della mossa minima esplorato per intero, senza finestra
deep            tutti gli scalini esplorati per intero, senza finestra
```

`smart_profile` (nuovo default) trova `d_min`, individua lo scalino della mossa minima, cerca soltanto dentro quello scalino e conserva le mosse con difficoltà `<= d_min + p`: la finestra non attraversa mai lo scalino. Esempio: se la tecnica minima è uno Swordfish (tier 1), la finestra resta dentro il tier 1 e non recluta una wing multicifra di rating vicino ma di tier 2.

`deep` esplora tutti gli scalini ordinari senza finestra, ma **non** include mai Complete Forcing Tree: non per un flag dedicato, ma perché l'albero completo resta un motore di fallback separato, invocato allo stesso modo per ogni `SearchPolicy` soltanto quando ordinary e Nested sono entrambi `EXHAUSTED` (architettura preesistente, confermata invariata).

### `SearchLimits`: `limited` / `unlimited`

Dimensione indipendente dalla `SearchPolicy`, componibile liberamente (`smart_profile+limited` è il default di produzione, `deep+unlimited` è per test/studio):

```text
result_limit          massimo numero di mosse restituite per tecnica
search_budget          nodi, profondità, diramazioni, sottoprove esplorabili
presentation_limit     quante mosse mostriamo/serializziamo
```

`result_limit` e `presentation_limit` non compromettono la mossa minima certificata. `search_budget` sì: se la ricerca viene fermata prima di poter concludere, il detector deve rispondere `TRUNCATED`, mai un `FOUND` silenzioso su una porzione incompleta dello spazio.

`unlimited` non significa "nessun limite di sistema": significa che nessun cap statico interno (risultati, profondità, nodi) altera la risposta logica. Restano sempre attivi cancellazione esterna, protezione della memoria e timeout espliciti. `unlimited` è oggi utile solo a scopo di test/studio, non è la modalità di produzione.

I `SearchLimits` fissi per detector (già esistenti: `MAX_MOVES_PER_TECHNIQUE`, budget ALS-AIC, budget Nested P16 ecc.) restano validi come default di `limited` e non dipendono dallo stato o dal puzzle.

### Contratto futuro (non ancora implementato in questa patch)

Predisporre soltanto la forma del contratto per la futura ricerca esaustiva mosse-per-tecnica, senza costruirne interfaccia o visualizzazione:

```text
search_moves(technique_id, cursor) -> moves, next_cursor, exhausted, truncated_reason
```

### `InferenceProfile`

```python
@dataclass(frozen=True)
class InferenceProfile:
    id: str
    allow_static_links: bool
    allow_dynamic_singles: bool
    allow_locked_candidates: bool
    allow_subsets: bool
    allow_basic_fish: bool
    allow_coloring: bool
    allow_group_nodes: bool
    allow_als: bool
    allow_nested_subproofs: bool
```

Configurazioni suggerite:

```text
static
dynamic
dynamic_plus
nested_level_1
nested_level_2
complete_tree
```

Ogni inferenza avanzata utilizzata dentro una catena deve conservare:

```text
technique_id
supporto
conclusione
sottoprova
costo
```

### Fedeltà della definizione Nested

Sudoku Explainer distingue le forcing chain ordinarie (regole basilari) dalle Advanced Forcing Chain (usano coppie, pointing, X-Wing ecc.) e definisce le Nested come "forcing chains within forcing chains": una deduzione interna alla catena è giustificata da un'altra catena. Non basta avere molte diramazioni, una chain lunga, una tecnica avanzata o propagazione dinamica: serve una sottoprova reale allegata a un'inferenza interna, condizione già resa autorevole in P16 (`nested_depth >= 1`, `nested_subproof_count >= 1`) e che P17 non deve indebolire.

### Criteri di completamento

* La mossa applicata è sempre la minima certificata, indipendentemente dalla `SearchPolicy` attiva.
* `FOUND` / `EXHAUSTED` / `TRUNCATED` sono rappresentati esplicitamente nei risultati dei detector, e `TRUNCATED` a monte declassa le mosse successive a "minime conosciute" non certificate.
* `search_tier` è derivato da campi già autorevoli del catalogo (non un secondo catalogo manuale) ed è validato: nessuna `strategy_id` priva di scalino.
* `smart_profile` non fa mai attraversare lo scalino dalla finestra `p`.
* Complete Forcing Tree resta il fallback separato dopo ordinary e Nested.
* `unlimited` non altera mai la risposta logica rispetto a `limited`, solo la possibilità di completarla.
* Una Dynamic ordinaria usa soltanto il proprio `InferenceProfile`.
* Una Plus dichiara esattamente quali regole avanzate ha usato.
* Una Nested non usa tecniche non consentite dal profilo e contiene sempre almeno una sottoprova reale.
* La difficoltà deriva dal profilo e dalla prova concreta.
* L'interfaccia può mostrare le tecniche interne.

### Stato di implementazione: completata

Implementati: `search_tier` (`technique_catalog.py`, validato, derivato da campi autorevoli), le cinque `SearchPolicy` in `collect_moves_for_analysis` (`superficial`, `smart_profile` nuovo default, `full_profile`, `smart_deep`, `deep`), rinominazione completa lato solver/web/archivio con alias legacy `profile`/`profilo` → `full_profile` (verificato su archivi online reali esistenti, filename e cache invariati per i dati già salvati).

Implementati anche il flag `certified` e l'esito tipizzato `FOUND` / `EXHAUSTED` / `TRUNCATED` per ogni detector interrogato. `techniques.detector_search_metadata` conserva `completion`, `search_truncated` e cause stabili in `truncated_reasons`; `_collect_from_runners` aggiunge conteggi, difficoltà minima trovata e `minimum_certification_affected`, quindi propaga il contratto fino a `collect_moves_for_analysis` e a ogni passo di `solve_and_log`.

La propagazione copre tutti i budget interni oggi presenti nei detector: limiti di fin, endo-fin e risultati del motore Fish; enumerazione, profondità, stati, tentativi e risultati delle ricerche ALS; pattern, tentativi e lunghezza dei percorsi Kraken; configurazioni Templates per cifra; lunghezza dei cammini statici e grouped del motore logico; profondità, predecessori, tentativi, branch, sottoprove, nodi e risultati Nested. I limiti di risultato censurano l'inventario e conservano la certificazione quando esiste già una mossa valida; i limiti che possono nascondere una tecnica più semplice rendono `certified: false`. Una ricerca troncata resta `TRUNCATED` anche quando ha prodotto mosse utili.

Completati `InferenceProfile`, il collegamento reale a Dynamic, Dynamic Plus e Nested, la registrazione delle regole interne usate e `SearchLimits` centralizzato. Le configurazioni `limited` e `unlimited` attraversano solver e detector senza modificare la `SearchPolicy`: la prima applica i budget di produzione, la seconda disattiva i cap interni per test e studio, conservando i limiti di presentazione. I cinque profili di ricerca hanno test con contratti distinti; `smart_deep` evita i detector esterni allo scalino certificato invece di eseguire una deep completa e filtrarla soltanto alla fine.

P17.1 e P17.2 restano patch autonome successive: la prima richiede il checkpoint progettuale sul Complete Forcing Tree, la seconda implementerà le famiglie acquisite da `Aggiunte.md`. La chiusura del P17 principale non anticipa le decisioni richieste da quei due punti.

---

## P17.1 Revisione del Complete Forcing Tree

### Checkpoint obbligatorio

Prima di iniziare questa patch bisogna fermarsi e discutere:

* strategia di branching;
* euristiche e ordine dei casi;
* comportamento predefinito nelle modalità profile e deep;
* cancellazione esplicita richiesta dall’utente;
* quantità di prova da mostrare nell’interfaccia;
* separazione tra ricerca autorevole e viste di presentazione.

### Obiettivo

Rendere il fallback finale il più possibile vicino a un ragionamento Sudoku: deterministico, ottimizzato, comprensibile e capace di completare ogni puzzle valido quando le tecniche precedenti non bastano.

La ricerca autorevole deve restare completa e senza cap interni che possano alterare il risultato. Eventuali timeout, cancellazioni o limiti operativi devono essere esterni, espliciti e discussi prima dell’implementazione. Non devono esistere troncamenti silenziosi della prova.

Il motore non deve essere un “andare a caso”: deve preferire branch informativi, riusare stati equivalenti e produrre un `ProofDAG` umano anche quando la ricerca sottostante è esaustiva.

### Implementazione completata

Il checkpoint ha fissato un branching ibrido e umano. Il motore sceglie la
domanda col minor numero di alternative, preferendo una cella a una
cifra-casa quando l'arita' coincide. Le domande cifra-casa coprono tutte le
posizioni residue della cifra in una riga, colonna o box. L'impatto della
propagazione risolve i pareggi successivi e l'ordine fail-first visita prima
contraddizioni e stati piu' ridotti senza escludere alcun caso.

Le cache SAT e UNSAT riusano stati equivalenti e pubblicano metriche leggere.
Il `ProofDAG` conserva l'intero albero autorevole, comprese tipo di branch e
alternative; `presentation_proof` e' una vista compatta derivata e collegata
tramite digest. Il callback pubblico `cancellation_check` interrompe la
ricerca dall'esterno, propaga `TRUNCATED` con
`external_cancellation`, scarta le mosse parziali e non alimenta le cache.
Il fallback mantiene la stessa posizione dopo ordinary e Nested in tutte le
`SearchPolicy`. Nessun controllo dell'interfaccia rientra in P17.1.

---

## P17.2 Tecniche aggiuntive da `Aggiunte.md`

### Collocazione

Questa patch va eseguita dopo la chiusura dei profili P17 e dopo il
checkpoint sul Complete Forcing Tree. Deve precedere la revisione editoriale
finale, cosi' ogni nuova tecnica entra direttamente nel contratto definitivo
di prove, spiegazioni e visualizzazioni.

`Aggiunte.md` e' una fonte progettuale del repertorio futuro. La TASSIONOMIA
resta la fonte autorevole degli identificatori, delle famiglie e dello stato
di implementazione: ogni tecnica acquisita da `Aggiunte.md` deve quindi
essere formalizzata li' prima di entrare nel catalogo eseguibile.

### P17.2a Aligned Exclusion moderna

Estendere il detector Aligned Pair/Triplet oggi disponibile affinche' gli
excluder possano essere ALS multicella reali, condivisi con il motore ALS:

* coppie base allineate e non allineate come casi specifici distinti;
* excluder costituiti da ALS di una o piu' celle;
* combinazioni con piu' ALS, conservando soltanto quelli necessari alla
  conclusione;
* gradi superiori a tre attraverso un motore parametrico e budget espliciti;
* `ProofDAG` con assegnazioni respinte, ALS usati e conclusione verificabile.

La versione locale gia' implementata resta un caso specifico valido. Il nome
moderno deve derivare dalla struttura effettivamente usata e non dalla sola
funzione che ha prodotto la mossa.

### P17.2b Exocet e jExocet

Introdurre un motore dedicato per il pattern Exocet descritto in
`Aggiunte.md`, separato da fish, template e forcing generico. La prima
versione deve formalizzare almeno:

* base cells e insieme delle base digits;
* target cells, companion e mirror cells;
* cross-lines, S-cells, cover-lines ed escape cells;
* validazione delle condizioni strutturali prima di qualunque eliminazione;
* regole di eliminazione implementate come casi specifici identificabili;
* payload strutturato e prova verificabile per ogni conclusione.

Le regole ancora ambigue nella fonte, compreso il Compatible Digit Check,
restano `planned` finche' definizione e fixture non sono sufficienti a
garantire la soundness.

### P17.2c Bowman's Bingo moderno

Implementare Bowman's Bingo come last resort logico distinto dalle Forcing
Net e dal Complete Forcing Tree. Una mossa Bowman's richiede una singola
asserzione iniziale la cui propagazione collega senza ambiguita' tutti i
candidati rimasti e determina una soluzione completa coerente della griglia.

Il motore deve conservare:

* asserzione iniziale e stato ON/OFF;
* conseguenze candidate-level;
* assenza di candidati non colorati o ambigui;
* assenza di contraddizioni;
* soluzione completa derivata;
* `ProofDAG` o rete equivalente capace di giustificare ogni assegnazione.

Il criterio globale della tecnica deve essere verificato esplicitamente. Una
semplice contraddizione locale continua a appartenere alla propria famiglia
di forcing.

### Criteri di completamento

* Le tre famiglie hanno identificatori e stato espliciti in TASSIONOMIA.
* Ogni variante implementata possiede fixture positiva, near miss e test di
  soundness contro la soluzione.
* Aligned Exclusion riusa gli ALS autorevoli e non ricostruisce una seconda
  definizione incompatibile.
* Exocet non produce eliminazioni da regole ancora ambigue o parziali.
* Bowman's Bingo prova realmente la copertura globale della griglia.
* Tutti i limiti computazionali propagano lo stato di troncamento P17.

### Implementazione completata

Aligned Exclusion usa direttamente `als.enumerate_als` e conserva gli ALS
minimi necessari a respingere le assegnazioni interessate da ogni
conclusione. Type 1 allineato, Type 2 non allineato, Triplet e forma
generalizzata hanno identità distinte. Il motore parametrico accetta gradi
superiori a tre e propaga i budget di grado, combinazioni, assegnazioni e
risultati.

Il detector Junior Exocet formalizza base cells, base digits, target,
companion, mirror, cross-line, S-cell, cover house ed escape cell. La Regola
1 è eseguibile e possiede un `ProofDAG` strutturale. Compatible Digit Check e
le Regole 3, 4, 5 e 8 hanno ID permanenti con stato `planned`, perché la fonte
acquisita non offre ancora condizioni sufficienti per una implementazione
affidabile.

Bowman's Bingo usa una singola asserzione ON e accetta il risultato soltanto
quando ogni candidato iniziale è colorato, ogni cella ha un solo candidato
ON, non esistono contraddizioni e la griglia derivata soddisfa tutte le 27
case Sudoku. Il `ProofDAG` conserva i parent di ogni conseguenza e tutte le
assegnazioni finali. I tre detector propagano cause `TRUNCATED` tipizzate.
Nessun controllo dell'interfaccia rientra in P17.2.

---

## P17.3 Revisione finale di spiegazioni e visualizzazioni

### Collocazione

Questa patch va eseguita dopo P10-P17 e dopo la revisione P16.5, quando ogni
motore definitivo espone pattern, supporti e prove strutturate. Va completata
prima di P18-P20, così archivio e API 1.0 congelano direttamente il formato
editoriale definitivo.

### Obiettivo

Rivedere una per una tutte le tecniche implementate e trasformare i dati
strutturali già disponibili in spiegazioni e visualizzazioni specifiche,
senza spostare logica autorevole fuori da pattern e `ProofDAG`.

### Problemi da chiudere

1. Ogni spiegazione deve nominare con precisione pattern, vincolo logico,
   candidati coinvolti e conseguenza, evitando testi generici ripetitivi.
2. Celle che implicano la mossa e celle modificate devono restare sempre
   semanticamente distinte, anche per Hidden Single, BUG, fish e forcing.
3. Ogni tecnica deve dichiarare ruoli candidato appropriati (`base`, `cover`,
   `fin`, `endo-fin`, `group`, `assumption`, `contradiction`, `target`).
4. BUG+1 e gli altri pattern globali devono visualizzare l'intera struttura,
   non soltanto la cella conclusiva.
5. Le frecce devono rappresentare soltanto inferenze dimostrate: verso unico,
   equivalenza esplicita, strong/weak link, contraddizione e link raggruppati.
6. Group Node, ALS, Kraken, Nested e Complete Tree devono poter mostrare i
   supporti interni senza trasformare una rete in una falsa catena lineare.
7. Le prove molto dense devono offrire progressione o filtraggio, soprattutto
   su telefono, invece di sovrapporre indiscriminatamente tutti gli archi.
8. Palette, legenda, dimensioni dei candidati e contrasto devono superare una
   revisione desktop/mobile e non affidarsi al solo colore.
9. I controlli del player devono restare fermi durante il cambio di passo,
   indipendentemente dalla lunghezza della spiegazione.
10. Test snapshot/DOM devono coprire almeno una tecnica per ogni famiglia e
    verificare coerenza fra spiegazione, evidenze, frecce e conclusioni.

### Criteri di completamento

* Tutte le tecniche attive hanno un template esplicativo specifico.
* Ogni elemento disegnato è derivabile da pattern o `ProofDAG`.
* Nessuna equivalenza viene dedotta automaticamente da un semplice strong link.
* Desktop e telefono conservano candidati e relazioni chiaramente leggibili.
* Il vocabolario editoriale e lo schema `visual_evidence` sono pronti al freeze.

---

# Blocco F: difficoltà, archivi e pubblicazione

## P18. Modello definitivo della difficoltà

### Obiettivo

Consolidare il modello già introdotto, separando definitivamente rating della tecnica e complessità della prova.

### Campi pubblici

```python
{
    "base_difficulty": 7.0,
    "proof_complexity_extra": 0.3,
    "technical_difficulty": 7.3,
    "rating_kind": "pseudo_se",
    "difficulty_model_version": "3.0.0",
}
```

Il nome pubblico `proof_complexity_extra` deve sostituire eventuali alias transitori soltanto in questa patch, insieme all’aggiornamento coordinato di solver, web e archivio.

### Regole

Per tecniche locali:

```python
technical_difficulty = base_difficulty
```

salvo piccoli modificatori parametrici espliciti.

Per catene:

```text
chain length
node count
group node count
ALS count
edge complexity
```

Per forcing:

```text
assumption count
branch count
leaf count
proof node count
```

Per Nested:

```text
nested depth
nested subproof count
branch count
total nested complexity
```

Per Complete Forcing Tree:

```text
states visited
maximum search depth
branch count
leaf count
```

Complete Tree usa una formula distinta e `rating_kind="project"`.

### Scala di riferimento

```text
1.0-2.5   elementari e direct
2.6-4.4   intersections, subset, fish base, pattern intermedi
4.5-6.4   uniqueness, coloring, complex fish, ALS locali
6.5-7.9   AIC, Nice Loop, grouped chains, exclusion avanzata
8.0-8.7   multiple forcing, templates, Kraken
8.8-9.4   dynamic forcing, Plus, forcing nets
9.5-12.9  Nested Forcing Chains
13.0+     Complete Forcing Tree
99.0      backtracking non spiegabile
```

### Criteri di completamento

* I valori SE ufficiali sono distinguibili dai pseudo-SE.
* Un valore pseudo-SE non viene presentato come rating SE originale.
* La difficoltà della prova non modifica il nome della tecnica.
* Le metriche di Complete Tree non vengono confrontate come se fossero metriche Nested.
* Tutti i risultati contengono la versione del modello.

---

## P19. Consolidamento degli archivi

### Obiettivo

Allineare gli archivi allo schema definitivo senza introdurre retrocompatibilità indefinita.

### Regole

Ogni analisi salvata deve contenere:

```python
technique_catalog_version
proof_schema_version
proof_metrics_version
difficulty_model_version
analysis_version
analysis_schema_version
```

Procedura:

1. Accettare direttamente soltanto gli schemi correnti.
2. Mantenere migrazioni esplicite esclusivamente per formati legacy ancora presenti nei fixture o negli archivi reali del repository.
3. Invalidare e ricalcolare le analisi quando cambia il comportamento del solver.
4. Non inventare metriche mancanti.
5. Rendere ogni migrazione mantenuta idempotente.
6. Rimuovere alias e percorsi di migrazione privi di dati reali da supportare.

### Criteri di completamento

* I record correnti effettuano round-trip senza perdita.
* Gli schemi incompatibili vengono rifiutati o ricalcolati esplicitamente.
* Nessun nome legacy viene usato come identificatore nuovo.
* La canonicalizzazione dei Sudoku resta invariata.
* Il codice di migrazione residuo è coperto da fixture reali.

---

## P20. Congelamento della versione 1.0

### Obiettivo

Trasformare il progetto aggiornato in una release stabile.

### API da congelare

```text
TechniqueDefinition
TechniqueRunner
ProofNode
ProofDAG
InferenceProfile
Move
collect_moves_for_analysis()
solve_and_log()
analyse_puzzle()
```

I nomi effettivamente esportati dal progetto prevalgono su alias teorici non presenti nel codice.

### Requisiti di rilascio

Ogni tecnica non astratta del catalogo deve trovarsi in uno dei seguenti stati:

```text
implemented
disabled
deprecated
```

Non devono restare entry `planned` incluse nella promessa della versione 1.0.

Ogni tecnica implementata deve avere:

```text
fixture positivo
near miss
test di soundness
test di simmetria
test di serializzazione della prova
test di classificazione specifica
```

Il catalogo finale deve essere esportabile come JSON per:

```text
interfaccia web
documentazione
archivio
visualizzazioni
API
```

### Condizioni definitive della 1.0

La versione 1.0 è pronta quando:

1. Nessuna tecnica è identificata tramite sottostringhe nel nome.
2. Ogni mossa possiede un `technique_id` stabile.
3. Ogni nome specifico deriva da una validazione strutturale.
4. Le metriche del motore non vengono sovrascritte dal renderer.
5. Tutte le prove avanzate usano `ProofDAG`.
6. Le Forcing Net sono distinte dalle catene.
7. Le vere Nested contengono almeno una sottoprova.
8. Complete Forcing Tree viene usato soltanto dopo ordinary e Nested.
9. Le tecniche di unicità richiedono unicità verificata.
10. Rating SE, pseudo-SE e project sono sempre distinguibili.
11. Gli archivi correnti sono versionati e riproducibili.
12. Nessuna tecnica promessa dal catalogo 1.0 è priva di implementazione o esplicitamente disabilitata.

---

# Sequenza consigliata delle release intermedie

| Versione | Patch incluse | Risultato                                                  |
| -------- | ------------- | ---------------------------------------------------------- |
| `0.8.5`  | P10-P11       | Fish e coloring completi                                   |
| `0.9.0`  | P12-P14       | AIC, Group Nodes, ALS e generalized wings                  |
| `0.9.5`  | P15-P17       | Forcing Net, Kraken, vere Nested e profili                 |
| `0.9.6`  | P17.1         | Complete Forcing Tree rivisto dopo checkpoint progettuale |
| `0.9.7`  | P17.2-P17.3   | Tecniche aggiuntive e revisione editoriale definitiva     |
| `0.9.8`  | P18-P19       | Difficoltà definitiva e archivi consolidati                |
| `1.0.0`  | P20           | API e tassonomia congelate                                 |

# Dipendenze principali

Le fondamenta P01-P16 sono già acquisite.

```text
P17 -> checkpoint P17.1
P17.1 -> P17.2
P17.2 -> P17.3
P17.3 -> P18
P18 -> P19
P19 -> P20
```

# Ordine pratico restante

```text
P17 Profili Dynamic, Plus e Nested, completata
P17.1 Revisione Complete Forcing Tree, completata
P17.2 Tecniche aggiuntive da Aggiunte.md, completata
P17.3 Revisione finale di spiegazioni e visualizzazioni
P18 Difficoltà definitiva
P19 Consolidamento archivi
P20 Release 1.0
```

Questa sequenza evita di riscrivere più volte gli stessi componenti. Le tecniche avanzate vengono costruite sopra il `ProofDAG` e i `chain_links` già disponibili; le Nested arrivano soltanto quando catene, gruppi, ALS e forcing sono formalizzati; il Complete Forcing Tree rimane un fallback estremo e viene rivisto soltanto dopo una decisione esplicita sui suoi default. La revisione editoriale finale arriva dopo tutti i motori, quando ogni tecnica può fornire supporti definitivi senza successive riscritture.


P21: Sistemare interfaccia
LA griglia cambia dimensione delle celle a seconda che ci si ao meno un numero nella riga colonna.
