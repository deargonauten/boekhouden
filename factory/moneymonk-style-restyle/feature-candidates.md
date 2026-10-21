# Feature candidates (to walk through with the user)

Source: reference screenshots (numbers = file names in the images directory) plus sensible additions for a SIMPLE single-user Dutch eenmanszaak tool. NOTHING here is built in the moneymonk-style-restyle run. Size: S = under a day, M = a few days, L = a week or more. "Backlog" = overlap with an item in `<repo>/backlog.md`. Recommendation: opnemen / later / niet.

Priority order within each theme is top to bottom. Overall priority top 5: 1 (dashboard), 6 (bank import), 7 (bank matching), 14 (BTW-aangifte), 21 (inkoop boeken vanuit inbox).

## A. Overzicht (dashboard)
1. **Startpagina met overzicht** - Eerste pagina met kaarten: te ontvangen/te betalen, BTW te betalen dit kwartaal, ongeboekte transacties, saldo per rekening. Screenshot 4. Size M. Backlog: "Dashboard". Recommendation: opnemen (grootste winst voor gebruiker zonder boekhoudkennis; bouwen nadat bank en facturen bestaan, eerst met inbox-aantallen).
2. **Grafiek omzet / kosten / winst per maand** - Staafgrafiek met totalen omzet, kosten, winst voor gekozen periode. Screenshot 4. Size M (eigen inline SVG, geen library). Backlog: "Dashboard" (deels) en "Reports". Recommendation: later.
3. **Tabel "Rekeningen" met saldo en aantal openstaande transacties** - Per bankrekening/kas saldo en teller. Screenshot 4. Size S (na bank). Backlog: deels "Dashboard". Recommendation: opnemen (samen met 1).
4. **Periodekeuze "t/m deze maand", jaarkeuze overal** - Een vaste keuze voor boekjaar/periode bovenin die alle schermen volgt. Screenshots 4, 5, 11. Size S. Backlog: geen. Recommendation: opnemen.
5. **Notificatiebel / "Nieuwe features"** - Meldingen over updates. Screenshots 4, 8. Size S. Backlog: geen. Recommendation: niet (lokale single-user app).

## B. Bank en kas
6. **Banktransacties importeren (CSV / MT940 / CAMT)** - Bestand slepen, transacties inlezen, dubbele herkennen. Screenshots 15, 16. Size L. Backlog: "Bank statement import". Recommendation: opnemen.
7. **Transacties koppelen aan factuur** - Per transactie een voorstel "Koppel aan factuur ..." op bedrag/IBAN/factuurnummer, met handmatig zoeken. Screenshots 5, 7. Size L. Backlog: "Bank reconciliation". Recommendation: opnemen.
8. **Tabblad "Te verwerken" per rekening** - Lijst met per rekening een teller van ongeboekte transacties; groene balk bij geboekt, filter op jaar/alles/rubriek/zoeken. Screenshots 4, 5. Size M. Backlog: "Bank reconciliation". Recommendation: opnemen (de restyle bereidt `row--done` en sticky pager voor).
9. **Direct boeken zonder factuur (rubriek + btw kiezen)** - Transactie boeken op een kostenrubriek met standaard btw-code (bijv. bankkosten, geen btw). Screenshot 5. Size M. Backlog: "Bank reconciliation" (direct-book). Recommendation: opnemen.
10. **Handmatig transactie toevoegen** - Tab "Handmatig" in het toevoegen-venster voor contant geld/kas. Screenshots 15, 16. Size S. Backlog: geen. Recommendation: opnemen.
11. **Bankkoppeling (automatisch ophalen)** - "Transacties ophalen" via PSD2-aanbieder. Screenshots 5, 15. Size L, extern abonnement nodig. Backlog: geen. Recommendation: niet (CSV-import is genoeg lokaal).
12. **Importgeschiedenis en suggestieregels** - Lijst van eerdere imports (terugdraaien) en regels als "omschrijving bevat X -> rubriek Y". Screenshot 14 (tabs). Size M. Backlog: "matching rules". Recommendation: later.
13. **Meerdere rekeningen (bank, kas, creditcard, spaar)** - Per rekening eigen lijst en saldo. Screenshots 4, 5. Size M. Backlog: onderdeel van bank import ("bankrekeningen"). Recommendation: opnemen.

## C. BTW
14. **BTW-aangifte per kwartaal** - Rubrieken 1a t/m 5g met omzet en btw, afgeleid uit de boekingen, Q1-Q4 tabs, per kwartaal/maand/jaar. Screenshots 11, 12. Size L. Backlog: "BTW-aangifte". Recommendation: opnemen (wettelijk de kern).
15. **Doorklikken naar onderliggende boekingen (oogje)** - Bij elke rubriek zien welke boekingen erin zitten. Screenshots 11, 12. Size M (bij 14). Backlog: onderdeel BTW. Recommendation: opnemen.
16. **Aangifte vastleggen en periode vergrendelen** - "Vastleggen" na afloop van het kwartaal, status "Verantwoord". Screenshot 11. Size M. Backlog: "period locking after filing". Recommendation: opnemen.
17. **Waarschuwing als stand afwijkt van vastgelegde aangifte + suppletie** - "Stand per vandaag" vs. ingediend, knop "Suppletie maken". Screenshot 11. Size M. Backlog: niet expliciet. Recommendation: later.
18. **PDF/overzicht downloaden voor invullen bij Belastingdienst** - Download van de aangifte. Screenshots 11, 12. Size S (bij 14). Backlog: "export for Belastingdienst". Recommendation: opnemen.
19. **ICP-opgaaf** - Opgave intracommunautaire leveringen. Screenshot 11 (tab). Size M. Backlog: onderdeel "BTW-aangifte". Recommendation: later (alleen als je aan EU-bedrijven levert).
20. **Btw-codes beheren (hoog/laag/0%/verlegd/EU/KOR)** - Lijst van codes met rubriek-koppeling. Screenshot 9 (Btw-codes tab). Size S. Backlog: deels "BTW-aangifte". Recommendation: opnemen (basis voor 14).

## D. Inkoop en verkoop
21. **Inkoopfactuur boeken vanuit uitgelezen bestand** - Naast het bestand een formulier: leverancier, nummer, datum, vervaldatum, regels met rubriek en btw, totalen; opslaan maakt factuur en boeking. Screenshot 8. Size L. Backlog: "Purchase booking flow". Recommendation: opnemen (volgende logische stap na inbox).
22. **Keuze "Nieuwe inkoopfactuur / Nieuwe verkoopfactuur / Bestaande inkoopfactuur"** - Een bestand aan een bestaande factuur hangen. Screenshot 8. Size M. Backlog: onderdeel 21. Recommendation: later.
23. **Bedragen exclusief of inclusief btw + regels samenvoegen** - Schakelaar en knop in het factuurformulier. Screenshot 8. Size S. Backlog: onderdeel 21. Recommendation: opnemen.
24. **Verkoopfacturen maken en versturen** - Wet OB-proof PDF, doorlopende nummering, betalingstermijn, herinneringen. Screenshots (menu "Facturen", 4). Size L. Backlog: "Sales invoices". Recommendation: opnemen.
25. **Offertes** - Offerte maken en omzetten naar factuur. Screenshots (menu). Size L. Backlog: geen. Recommendation: niet nu (later als facturen er zijn).
26. **Producten/diensten-lijst** - Vaste regels met prijs en btw voor facturen. Screenshots (menu "Producten"). Size S. Backlog: geen. Recommendation: later.
27. **Te ontvangen / vervallen / te betalen / openstaand (debiteuren, crediteuren)** - Overzicht van openstaande facturen met vervallen bedragen. Screenshot 4. Size M. Backlog: onderdeel "Sales invoices"/"Dashboard". Recommendation: opnemen.
28. **Orders, projecten, uren, ritten, beloningsprogramma** - Project- en tijdsregistratie. Screenshots 4, 13 (menu). Size L. Backlog: alleen "urenregistratie (urencriterium)". Recommendation: niet, behalve urenregistratie voor het urencriterium (later).

## E. Bestanden en documenten
29. **Bestandenlijst met voorbeeld, hernoemen, downloaden, naar prullenbak** - Documentenbeheer met PDF-preview en acties. Screenshot 8. Size M. Backlog: geen (alleen "never deleted"; prullenbak past niet bij de bewaarplicht, dus "verbergen" in plaats van verwijderen). Recommendation: later (verbergen, nooit verwijderen).
30. **E-mail-intake** - Bijlagen uit eigen mailbox in de inbox. Screenshots: niet te zien, wel passend. Size L. Backlog: "Email intake". Recommendation: opnemen.
31. **Bestand verwerken met bestand links, formulier rechts, en volgende bestand in de lijst** - Een verwerk-weergave die door de inbox loopt. Screenshot 8. Size M. Backlog: deels bestaand review-scherm. Recommendation: later (na 21).

## F. Grootboek en instellingen
32. **Standaard btw-code per grootboekrekening** - Bij elke kostenrekening een standaard btw-percentage dat als suggestie dient. Screenshot 9. Size S. Backlog: "learned supplier->grootboek defaults" (verwant). Recommendation: opnemen (past precies bij "defaults voorstellen").
33. **"Selecteerbaar bij" (rekening alleen tonen bij inkoop/bank/facturen)** - Kortere keuzelijsten. Screenshot 9. Size S. Backlog: geen. Recommendation: opnemen (minder keuze = makkelijker).
34. **RGS indelen met accepteren/afwijzen van suggesties** - Per rekening RGS-code voorstellen. Screenshot 10. Size M. Backlog: "RGS mapping". Recommendation: later (eerst de backlog-controle van codes).
35. **Bedrijfsgegevens** (naam, adres, KvK, BTW-id, IBAN) - Eigen gegevens die op facturen en aangifte komen. Screenshot 13. Size S. Backlog: nodig voor "Sales invoices". Recommendation: opnemen.
36. **Openingsbalans** - Beginstanden invoeren bij start. Screenshot 13 (menu). Size M. Backlog: geen. Recommendation: opnemen (nodig voor wie halverwege het jaar start).
37. **Memoriaalboekingen apart overzicht** - Handmatige boekingen in eigen tab. Screenshot 9 (tabs). Size S. Backlog: bestaat deels (Boeken met dagboek-filter). Recommendation: niet (dagboek-tabs doen dit al).
38. **Groepen en IB-indeling van rekeningen** - Rekeningen indelen voor IB-aangifte. Screenshot 9 (tabs). Size M. Backlog: "IB-voorbereiding export". Recommendation: later.
39. **Gebruikers, abonnement, e-mails instellen** - Multi-user beheer. Screenshot 13. Size M. Backlog: geen. Recommendation: niet (single-user, lokaal).

## G. Automatisering
40. **Boekhoudrobot: per type automatisch boeken (handmatig of automatisch)** - Instelling per soort transactie (eigen rekeningen, btw-betaling, openstaande verkoop-/inkoopfacturen). Screenshot 14. Size M (na 6 en 7). Backlog: "matching rules". Recommendation: later (pas als handmatig koppelen goed werkt; voorstel-en-bevestig blijft de standaard).
41. **Leren van eerdere keuzes (leverancier -> rubriek en btw)** - Volgende factuur van dezelfde leverancier krijgt automatisch dezelfde voorstellen. Screenshot 14 (suggestieregels). Size M. Backlog: onderdeel "Purchase booking flow". Recommendation: opnemen.
42. **Automatisch BTW-betaling herkennen** - Betaling aan Belastingdienst koppelen aan vastgelegde aangifte (rekeningnummer + betalingskenmerk). Screenshots 5, 14. Size M. Backlog: geen. Recommendation: later.

## H. Rapportages en eenmanszaak
43. **Rapportages (W&V, balans, proef- en saldibalans, grootboekkaart)** - Standaardoverzichten met vergelijking met vorig jaar. Screenshots (menu "Rapportages"). Size L. Backlog: "Reports". Recommendation: opnemen.
44. **Bezittingen en afschrijvingen** - Activa met automatische afschrijving. Screenshots (menu "Bezittingen"). Size L. Backlog: "Fixed assets". Recommendation: later.
45. **Privé-onttrekkingen en stortingen, winst uit onderneming** - Eenmanszaak-specifiek jaarwerk. Screenshot 9 (rekening "Privé"). Size M. Backlog: "Eenmanszaak year-end". Recommendation: opnemen.
46. **Kilometervergoeding en ritten** - Rekening "Kilometervergoeding" met ritregistratie. Screenshots 4, 9. Size M. Backlog: geen. Recommendation: later (alleen als zakelijke km voor jou speelt).

## I. Gebruiksgemak en veiligheid (eigen aanvullingen)
47. **Uitleg-pagina met alle begrippen + ronde "?"-knop** - Wordt in de restyle-run al gebouwd. Screenshots 4 t/m 16 (ronde blauwe knop). Size S. Backlog: nieuw, hoort bij "Plain-language pass". Recommendation: al gedaan in deze run.
48. **Controle voordat je aangifte doet ("Klopt dit?")** - Lijst met waarschuwingen: ongeboekte transacties, boekingen zonder document, onevenwichtige periodes. Size M. Backlog: geen. Recommendation: opnemen (goed voor niet-boekhouders).
49. **Back-up en export in een klik** - Database en documenten. Size M. Backlog: "Backup & export". Recommendation: opnemen.
50. **Zoeken over alles (relaties, boekingen, bestanden)** - Een zoekveld bovenin. Size M. Backlog: geen. Recommendation: later.
