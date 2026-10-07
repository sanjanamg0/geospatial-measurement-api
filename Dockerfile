FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

# pyogrio / pyproj / shapely ship manylinux wheels that bundle GDAL, GEOS and PROJ,
# so no system geospatial packages are needed.
COPY requirements.txt requirements-optional.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-optional.txt gunicorn

COPY manage.py .
COPY geoproject ./geoproject
COPY measurements ./measurements

ENV GEO_DATA_DIR=/data DJANGO_DEBUG=0
VOLUME /data
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn geoproject.wsgi --bind 0.0.0.0:8000"]
