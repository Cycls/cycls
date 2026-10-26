# Résumé : une section « Apps » native dans le SDK Cycls

**Branche locale** `proposal/apps-catalog`, partie de `8156ad52` (le commit « release: 0.0.2.147 »
qui correspond à la version publiée sur PyPI ; le dépôt n'a pas de tags). Rien n'a été poussé, aucune PR
n'a été ouverte, rien n'a été déployé, aucun agent en production n'a été touché.

**Ce que ça fait**
- Un agent déclare son catalogue d'apps avec `cycls.Web().apps("default_apps")` : un dossier de bundles
  déjà construits, copié dans l'image.
- Un admin de l'espace de travail installe, met à jour ou retire une app d'un clic. « Retirer » met
  l'app à la corbeille, comme une suppression. Une app créée par une personne n'est jamais écrasée : le
  serveur répond 409.
- Thème par espace de travail : couleur de base shadcn (neutral, zinc, slate, stone), accent (blue,
  green, orange, red, rose, violet, yellow), arrondi, et une couleur de marque en option. Toute app
  shadcn change d'apparence **en direct, sans rebuild**, y compris celles déjà ouvertes.
- Côté interface : une entrée « Apps › » sous « Skills » dans le menu +, avec un sous-menu (les apps
  installées, puis « Parcourir les apps… »). Dans la fenêtre des connecteurs, un onglet « Apps » sous
  « Skills », avec deux vues, « Parcourir » et « Thème », et un aperçu clair/sombre. Tout fonctionne en
  arabe (RTL) et sur téléphone.

**Le code a tranché sur un point**
Le brief plaçait le thème dans le slot `.settings`. Or ce slot est **par personne**, pas par espace de
travail. Le thème est donc stocké dans le slot `.apps` de l'espace (clé `.theme`).

**Un vrai bug du SDK, corrigé au passage**
Retirer une app, la réinstaller, puis vider la corbeille effaçait les données de l'app réinstallée.
`build_app` avait le même problème. Un test le prouve : il échoue sans la correction.

**Tests**
- Python : 35 nouveaux tests passent. La suite complète a les mêmes 14 échecs qu'avant mes changements,
  tous propres à Windows.
- Client : 413 tests sur 413 passent, et `tsc` ne signale aucune erreur.

**Captures**
17 captures dans `screenshots/` : le menu +, le catalogue, la vue d'un membre non admin, le mode sombre,
le panneau Thème, l'app Tâches dans 4 apparences (dont un changement de thème poussé en direct), l'arabe
et le téléphone. Elles viennent des vrais composants du client, branchés sur une API simulée
(`harness/`), avec l'app Tâches construite à partir du kit patché (`kit-patch/`, une copie ; le kit
d'origine n'a pas été modifié).

**Pas fait**
- Pas de vrai `cycls run` avec connexion Clerk.
- Pas de test sur l'app mobile ni sur GCS.
- Le bundle `themes/default` n'a pas été reconstruit : c'est le travail de l'étape de publication.

**À décider (détail dans README.md)**
- Préinstaller certaines apps pour les nouveaux espaces de travail.
- Que faire quand on réinstalle une app encore dans la corbeille.
- Qui peut installer dans une organisation sans espaces de travail.
- Servir le catalogue depuis le CMS ou un bucket, comme la bibliothèque de Skills.

README.md liste aussi 7 problèmes du SDK trouvés en chemin : `value` non typé, pas d'écriture
`cycls.me` pour l'agent, pas de `put` en création seule, `write: admin` contournable via `/files`,
plafond de 10 000 lignes sans curseur, `/app` en tmpfs.
