# Silo pour Home Assistant

[![Tests](https://github.com/TheBarnHome/silo-ha-integration/actions/workflows/tests.yml/badge.svg)](https://github.com/TheBarnHome/silo-ha-integration/actions/workflows/tests.yml)
[![hassfest](https://github.com/TheBarnHome/silo-ha-integration/actions/workflows/validate.yml/badge.svg)](https://github.com/TheBarnHome/silo-ha-integration/actions/workflows/validate.yml)

Intégration Home Assistant pour [Silo](https://siloserver.org/), pensée pour
retrouver ce que fournit l'intégration Plex : savoir qui lit quoi, sur quel
appareil, et piloter la lecture depuis Home Assistant.

> *English summary: a Home Assistant custom integration for the Silo media
> server. It exposes one `media_player` per playing Silo client (title, series,
> season/episode, position, user, device, play method, node), a watching counter
> and library statistics, plus pause/resume/stop/message/terminate commands
> through Silo's administrator playback API.*

## Ce que l'intégration expose

| Type | Entité | Contenu |
| --- | --- | --- |
| `media_player` | une par client Silo (compte + application + plateforme) | état `playing` / `paused` / `idle`, titre, série, saison, épisode, position, durée, poster presigné, utilisateur, profil, client, IP, méthode de lecture, node, codecs/bitrates source et cible, transcodage matériel |
| `sensor` | « En lecture » | nombre de sessions live |
| `sensor` | Films, Séries, Fichiers, Utilisateurs, Stockage | statistiques du tableau de bord Silo |
| services | `silo.send_message` | affiche un message sur le player d'une session |
| services | `silo.terminate_session` | révoque l'autorité d'une session (plus dur qu'un stop) |
| services | `silo.scan_library` | lance un scan de bibliothèque |

## Parité avec Plex : ce qui existe, ce qui manque

L'API d'administration de Silo expose les observations de lecture et cinq
commandes séquencées. Elle n'expose **pas** ce que l'API Plex permet :

| Fonction | Plex | Silo |
| --- | --- | --- |
| Voir la lecture en cours, l'appareil, l'utilisateur | ✅ | ✅ |
| Titre, série, saison, épisode, position, durée | ✅ | ✅ |
| Pause / reprise / stop | ✅ | ✅ |
| Message sur le player | ❌ | ✅ (`silo.send_message`) |
| Révocation d'autorité | ❌ | ✅ (`silo.terminate_session`) |
| Chercher une position (seek) | ✅ | ❌ absent de l'API admin |
| Volume / mute | ✅ | ❌ absent de l'API admin |
| Piste suivante / précédente | ✅ | ❌ absent de l'API admin |
| Lancer un média sur un client (`play_media`) | ✅ | ❌ absent de l'API admin |
| Navigation de médiathèque (`browse_media`) | ✅ | ❌ |
| Note, résumé, bibliothèque d'origine | ✅ | ❌ absents des sessions Silo |

Les commandes manquantes existent pourtant dans le protocole temps réel de Silo
(`seek`, `set_volume`, `play_media`), mais le socket de contrôle appartient au
propriétaire de la session : s'y connecter couperait la voie temps réel du
lecteur en cours. Elles demanderaient une évolution amont de l'API
d'administration — l'intégration n'active donc que ce que le serveur annonce
dans `GET /api/v2/admin/sessions/command-capabilities`.

## Prérequis

- **Silo** servant son API native `/api/v2` (vérifié sur `build-1727`, commit
  `8cbc8202`) ;
- **Home Assistant 2026.10** ou plus récent (Python 3.14) ;
- une **clé API Silo non scopée appartenant à un compte administrateur**.

Pourquoi administrateur et non scopée : la vue des sessions live
(`/api/v2/admin/sessions`) et les commandes ne sont ouvertes qu'aux
administrateurs, et le catalogue de scopes de Silo ne contient aujourd'hui que
`admin:users`, `admin:access-groups:read`, `admin:sessions:summary:read` et
`libraries:read` — aucun scope ne couvre le détail des sessions ni le contrôle.

## Installation

1. HACS → menu ⋮ → **Dépôts personnalisés** → ajouter
   `https://github.com/TheBarnHome/silo-ha-integration`, catégorie
   **Integration**.
2. Installer **Silo**, puis redémarrer Home Assistant.
3. Paramètres → Appareils et services → **Ajouter une intégration** → *Silo*.

## Configuration

| Champ | Valeur |
| --- | --- |
| URL du serveur | `http://silo.silo.svc.cluster.local` (réseau du cluster, sans repasser par Traefik) ou `https://silo.example.tld` |
| Clé API | Silo → Administration → Clés API → nouvelle clé, libellé `home-assistant`, **sans scope** |
| Vérifier le certificat TLS | à désactiver uniquement pour une URL HTTP interne ou un certificat auto-signé |

Options (rechargées sans redémarrage) :

- **Intervalle d'interrogation** : 2 à 300 s, 10 s par défaut (2 s pour un
  déclenchement quasi immédiat au démarrage et à l'arrêt d'une lecture). Silo n'ouvre pas
  son socket d'événements aux clés API (`/api/v2/events/ws-ticket` les refuse),
  les sessions sont donc interrogées par polling : une commande partie d'ailleurs
  peut mettre jusqu'à un intervalle à apparaître.
- **Capteurs de bibliothèque** : films, séries, fichiers, utilisateurs, stockage.
- **Utilisateurs inclus / ignorés** : noms de compte séparés par des virgules.

## Fonctionnement

- Le nom d'une entité ne contient ni version ni build de l'application
  (`Tristan · Silo iPhone (iOS)`, pas `… 1.1.0 (build 68)`) : une mise à jour
  du client ne la renomme pas. Les identifiants créés avant la 0.2.0 sont
  réécrits au démarrage dès que le client rejoue.
- Une entité est créée par couple **(compte, nom du client, plateforme)** et
  conservée en `idle` entre deux lectures, comme l'intégration Plex conserve ses
  clients. Ses `entity_id` restent stables après un redémarrage de Home
  Assistant.
- Silo ne fournit **aucun identifiant d'appareil** sur les sessions natives ;
  la plateforme est déduite du `User-Agent` (`macOS`, `iOS`, `Android`,
  `Apple TV`, `webOS`, `Windows`, `Linux`…). Deux appareils identiques du même
  compte peuvent donc fusionner — les attributs `client_ip`,
  `client_label_full` et `client_user_agent` permettent de les distinguer.
- Les commandes sont séquencées comme l'exige Silo : un `command_id` UUID par
  action et une séquence strictement croissante. Si le serveur répond `409` avec
  l'en-tête `X-Silo-Latest-Sequence` (séquence périmée, par exemple après un
  redémarrage de Home Assistant), la commande est rejouée une fois au-dessus de
  la séquence annoncée.

## Dépannage

| Symptôme | Cause probable |
| --- | --- |
| `invalid_auth` à l'ajout | clé révoquée, mal copiée, ou compte désactivé |
| `not_admin` | la clé appartient à un compte non administrateur |
| `unsupported_api` | serveur qui ne sert pas `/api/v2` (build trop ancien) |
| `cannot_connect` | URL inaccessible depuis le pod Home Assistant, TLS, DNS |
| Entités `idle` alors que Silo lit | intervalle trop long, filtre utilisateurs, ou lecture faite par un client authentifié sur un autre serveur Silo |
| Pause refusée (`Silo refused the command`) | la session n'a pas de voie temps réel ouverte : le serveur refuse la commande plutôt que de la simuler |
| `rate limited` | budgets Silo épuisés (6000 req/min par adresse par défaut) |

Diagnostics : Paramètres → Appareils et services → Silo → *Télécharger les
diagnostics* (la clé API y est expurgée).

## Sécurité

La clé API est un **administrateur complet** de Silo. Elle est stockée dans le
`config_entry` de Home Assistant, jamais dans Git. En cas de fuite ou de doute :
révoquer la clé dans Silo (le flux de réauthentification de l'intégration
propose alors une nouvelle clé) et en créer une autre.

## Développement

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest tests -q
.venv/bin/ruff check custom_components tests
.venv/bin/ruff format --check custom_components tests
```

La suite de tests couvre le client HTTP (pagination, erreurs, séquences), le
modèle de session (clé d'entité, plateforme, parsing tolérant), le coordinator,
les plateformes et les flux de configuration, sur des fixtures calquées sur les
contrats `contracts/api/v2/fixtures/` de Silo.

## Licence

MIT — voir [LICENSE](LICENSE).
