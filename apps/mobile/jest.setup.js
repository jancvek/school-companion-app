// React 19 zahteva to zastavico, sicer vsak setState zunaj act(...) izpiše
// opozorilo, čeprav ga @testing-library/react-native pravilno zavije.
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
