# Run cBioPortal using Docker Compose
Download necessary files (seed data, example config and example study from
datahub):
```
./init.sh
```

Start docker containers. This can take a few minutes the first time because the
database needs to import some data.
```
docker-compose up
```
In a different terminal import a study
```
docker-compose run cbioportal metaImport.py -u http://cbioportal:8080 -s study/lgg_ucsf_2014/ -o
```

Restart the cbioportal container after importing:
```
docker-compose restart cbioportal
```

The compose file uses docker volumes which persist data between reboots. To completely remove all data run:

```
docker compose down -v
```
