# wpp-drive-mapper-and-launcher - Mappatore automatico di cartelle su lettere di unità

## Descrizione

**wpp-drive-mapper-and-launcher.exe** è un'utility Windows che legge tutte le sottocartelle
presenti nella sua stessa directory e le mappa automaticamente come unità
virtuali tramite il comando `subst`.

## Logica di assegnazione lettere

| Tipo di cartella | Prima scelta | Fallback |
|---|---|---|
| Nome = **1 lettera** (es. `D`) | La lettera del nome (es. `D:`) | Da `Z:` a ritroso |
| Nome = **più lettere** (es. `Tools`) | Da `X:` a ritroso (X, W, V…) | Continua a scendere |

La lettera `C:` è sempre riservata al sistema
e non viene mai usata nemmeno come fallback.

## Avvio automatico di winPenPack

Dopo aver mappato ogni cartella, il programma verifica se nella nuova
unità esiste il file `winPenPack.exe`. In caso affermativo, lo avvia
automaticamente.

## Compilazione in EXE

### Requisiti
- Python 3.x installato
- PyInstaller (`pip install pyinstaller`)

### Istruzioni
1. Posiziona `folder_subst.py` e `build.bat` nella stessa cartella
2. Esegui `build.bat` (doppio clic)
3. L'EXE monolitico sarà in `dist\wpp-drive-mapper-and-launcher.exe`

### Comando manuale
```
pyinstaller --onefile --console --name "wpp-drive-mapper-and-launcher" folder_subst.py
```

## Utilizzo

1. Copia `wpp-drive-mapper-and-launcher.exe` nella cartella "radice" che contiene le sottocartelle
2. Esegui `wpp-drive-mapper-and-launcher.exe` **come Amministratore** (subst richiede privilegi)
3. Il programma mappa le cartelle e avvia winPenPack.exe se presente

## Esempio

```
C:\PortableApps\
├── wpp-drive-mapper-and-launcher.exe
├── D\                  <- nome 1 lettera → prova D:, se occupata usa Z:
├── Tools\              <- nome lungo → usa X: (o W:, V:, ...)
└── Firefox\            <- nome lungo → usa lettera successiva disponibile
```

Output esempio:
```
Cartella base: C:\PortableApps

Lettere già in uso: A, B, C, D

Elaborazione cartella: 'D'
  -> Tentativo lettera preferita 'D': già in uso
  -> Assegnata unità Z: -> C:\PortableApps\D
  -> winPenPack.exe non trovato su Z:\

Elaborazione cartella: 'Firefox'
  -> Assegnata unità X: -> C:\PortableApps\Firefox
  -> winPenPack.exe non trovato su X:\

Elaborazione cartella: 'Tools'
  -> Assegnata unità W: -> C:\PortableApps\Tools
  -> Avviato: W:\winPenPack.exe
```

## Note

- Le unità mappate con `subst` sono **temporanee** e spariscono al riavvio
- Per rimuovere manualmente una mappatura: `subst X: /D`
- Il programma non rimuove mappature precedenti; se una lettera è già in uso, passa alla successiva
