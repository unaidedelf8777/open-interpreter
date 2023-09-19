# Base image
FROM debian:bullseye

# Set environment variables to disable prompts
ENV DEBIAN_FRONTEND=noninteractive

# Update package list and install essential utilities and runtimes
RUN apt-get update && apt-get install -y \
    jq \
    build-essential \
    python3 \
    python3-pip \
    python3-dev \
    curl \
    libssl-dev \
    libexpat1 \
    r-base \
    r-base-dev

# Install NodeJS
RUN curl -sL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs

# Copy unified requirements.txt into the image
COPY ./requirements.txt /tmp/

# Install Python packages
RUN awk '/\[python\]/, /^\s*$/' /tmp/requirements.txt | grep -v '^\[python\]' > /tmp/python_requirements.txt && \
    pip3 install --no-cache-dir -r /tmp/python_requirements.txt --no-input

# Create an initial empty package.json
RUN echo '{}' > /tmp/package.json

# Populate package.json with dependencies from node_requirements.txt
RUN awk '/\[node\]/, /^\s*$/' /tmp/requirements.txt | grep -v '^\[node\]' > /tmp/node_requirements.txt && \
    while read -r package; do \
        echo $package | grep -Eo "^[a-zA-Z0-9_-]+" | xargs -I {} sh -c 'jq ".dependencies.\"{}\" = \"*\"" /tmp/package.json > /tmp/package_temp.json && mv /tmp/package_temp.json /tmp/package.json'; \
    done < /tmp/node_requirements.txt

# Install NodeJS packages
RUN npm install --save --yes --no-package-lock --prefix /tmp

# Install R packages
RUN awk '/\[r\]/,/^\s*$/' /tmp/requirements.txt | sed 's/^\[r\]//' > /tmp/r_requirements.txt && \
    while read p; do R -e "install.packages('$p', repos='http://cran.rstudio.com/', dependencies=TRUE, INSTALL_opts = c('--no-tests'))"; done < /tmp/r_requirements.txt

# Remove temporary files
RUN rm /tmp/package.json /tmp/node_requirements.txt /tmp/python_requirements.txt /tmp/r_requirements.txt

# Set work directory
WORKDIR /mnt/data
