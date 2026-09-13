FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir flask python-escpos Pillow
COPY app.py template_core.py raster.py usb_devices.json /app/
COPY templates/ /app/templates/
COPY web/ /app/web/
EXPOSE 5051
CMD ["python", "app.py"]
