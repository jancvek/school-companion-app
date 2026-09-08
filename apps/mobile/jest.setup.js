// React 19 zahteva to zastavico, sicer vsak setState zunaj act(...) izpiše
// opozorilo, čeprav ga @testing-library/react-native pravilno zavije.
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/**
 * Omrežje je v testih zaprto.
 *
 * „Testi ne kličejo omrežja" mora biti lastnost zbirke, ne lastnost
 * discipline pri pisanju posameznega testa. Od V1-R07 ponudnik sinhronizacije
 * sam sestavi odjemalca za arhiv, kadar mu ga test ne poda — in ta bi brez te
 * ograje na svežem klonu zares poklical naslov iz gradnje.
 *
 * Test, ki omrežje potrebuje, si `fetch` podtakne sam.
 */
globalThis.fetch = () => {
  throw new Error('Test je poskusil na omrežje. Podtakni odvisnost namesto tega.');
};
