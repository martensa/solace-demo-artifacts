#!/bin/bash

# ============================
#  GENERIC ENTITY SETUP + BUILD + CURL TRIGGER + PACKAGING
# ============================
DOCKER_ENTITY_PATH="/app/cli/src/main/java"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

HIBERNATE_FILE="$SCRIPT_DIR/src/main/resources/hibernate.properties"
REVENG_FILE="$SCRIPT_DIR/src/main/resources/reveng.xml"
GENERATOR_JAR="$SCRIPT_DIR/generate-entities-cli-1.0-SNAPSHOT.jar"
PACKAGER_JAR="$SCRIPT_DIR/package-jar-cli-1.0-SNAPSHOT.jar"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[1;36m'; NC='\033[0m'

# Detect OS and choose correct sed command
if [[ "$OSTYPE" == "darwin"* ]]; then
  SED_CMD="sed -i ''"
else
  SED_CMD="sed -i"
fi

echo -e "${YELLOW}--------------------------------------------"
echo -e "   Hibernate Entity Generator Setup"
echo -e "--------------------------------------------${NC}"

# -----------------------------
#       USER INPUT
# -----------------------------
read -p "Enter JDBC Driver Class (e.g. org.postgresql.Driver): " DB_DRIVER

echo ""
echo "Enter JDBC URL"
echo "Examples:"
echo "  PostgreSQL: jdbc:postgresql://host:5432/dbname"
echo "  Oracle    : jdbc:oracle:thin:@host:1521/service"
echo ""
read -p "JDBC URL: " JDBC_URL

read -p "Enter DB Username: " DB_USER
read -sp "Enter DB Password: " DB_PASS
echo ""

read -p "Enter Schema Name: " SCHEMA_NAME
read -p "Enter Hibernate Dialect: " DB_DIALECT

read -p "Enter Output Package (e.g. com.solace.test): " PACKAGE_NAME
PACKAGE_PATH_FORMATTED="${PACKAGE_NAME//./\/}"

read -p "Enter Output Directory (absolute path): " OUTPUT_DIR

echo ""
echo -e "${YELLOW}Updating configuration files...${NC}"

# -----------------------------
#  UPDATE hibernate.properties
# -----------------------------
if [[ -f "$HIBERNATE_FILE" ]]; then
  cat > "$HIBERNATE_FILE" <<EOF
hibernate.connection.driver_class=$DB_DRIVER
hibernate.connection.username=$DB_USER
hibernate.connection.password=$DB_PASS
hibernate.connection.url=$JDBC_URL
hibernate.default_schema=$SCHEMA_NAME
EOF

  echo -e "${GREEN}✔ Updated $HIBERNATE_FILE${NC}"
else
  echo -e "${RED}✘ ERROR: $HIBERNATE_FILE not found.${NC}"
  exit 1
fi

# -----------------------------
#  UPDATE reveng.xml
# -----------------------------
if [[ -f "$REVENG_FILE" ]]; then
  # Remove existing schema-selection node
  $SED_CMD '/<schema-selection/d' "$REVENG_FILE"

  # Insert new schema-selection before closing tag
  if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS sed format (requires newline and escape)
    sed -i '' "/<\/hibernate-reverse-engineering>/i\\
    \ \ \ \ <schema-selection match-schema=\"$SCHEMA_NAME\"\/>
    " "$REVENG_FILE"
  else
    # Linux sed format
    sed -i "/<\/hibernate-reverse-engineering>/i \    <schema-selection match-schema=\"$SCHEMA_NAME\"\/>" "$REVENG_FILE"
  fi

  echo -e "${GREEN}✔ Updated schema in $REVENG_FILE${NC}"
else
  echo -e "${RED}✘ ERROR: $REVENG_FILE not found.${NC}"
  exit 1
fi


# -----------------------------
#  RUN ENTITY GENERATOR JAR
# -----------------------------
echo ""
echo -e "${CYAN}--------------------------------------------"
echo -e " Running Entity Generator (ALL TABLES)"
echo -e "--------------------------------------------${NC}"

java -jar "$GENERATOR_JAR" \
  -c "$HIBERNATE_FILE" \
  -r "$REVENG_FILE" \
  -o "$OUTPUT_DIR" \
  -p "$PACKAGE_NAME"

if [[ $? -ne 0 ]]; then
  echo -e "${RED}✘ Entity generation failed.${NC}"
  exit 1
fi

echo -e "${GREEN}✔ Entity generation completed successfully${NC}"

# -----------------------------
#  TABLE NAME INPUT
# -----------------------------
echo ""
read -p "Enter table name for CURL request: " TABLE_INPUT
[[ -z "$TABLE_INPUT" ]] && { echo -e "${RED}✘ Table name required.${NC}"; exit 1; }

# -----------------------------
#  STRATEGY
# -----------------------------
echo ""
echo "  1) readingIndicator"
echo "  2) timestamp"
echo "  3) sequential"
read -p "Enter strategy (1/2/3): " STRATEGY_CHOICE

case "$STRATEGY_CHOICE" in
  1) STRATEGY="readingIndicator" ;;
  2) STRATEGY="timestamp" ;;
  3) STRATEGY="sequential" ;;
  *) echo -e "${RED}✘ Invalid option.${NC}"; exit 1 ;;
esac

UPPER_STRATEGY=$(echo "$STRATEGY" | tr '[:lower:]' '[:upper:]')
echo -e "${GREEN}✔ Strategy selected: $STRATEGY${NC}"

# -----------------------------
#  CHILD TABLES
# -----------------------------
read -p "Enter child table names (comma-separated, optional): " CHILD_TABLE_INPUT
CHILD_TABLES=$(echo "$CHILD_TABLE_INPUT" | tr -d ' ')

# -----------------------------
# AUTO POPULATE
# -----------------------------
read -p "Allow NOT NULL auto population? (true/false): " ALLOW_NOT_NULL
[[ "$ALLOW_NOT_NULL" != "true" && "$ALLOW_NOT_NULL" != "false" ]] && { echo -e "${RED}Invalid value.${NC}"; exit 1; }
AUTO_POPULATE=$ALLOW_NOT_NULL

# -----------------------------
# CUSTOM CONFIG (if needed)
# -----------------------------
CUSTOM_CONFIG=""
if [[ "$AUTO_POPULATE" == "false" ]]; then
  read -p "Enter CUSTOM_CONFIGURATION (<TABLE>.<COL>,...): " CUSTOM_CONFIG
fi

# -----------------------------
# STRATEGY INDICATOR
# -----------------------------
read -p "Enter DB_READ_RECORD_${UPPER_STRATEGY}_INDICATOR value: " STRATEGY_INDICATOR

# -----------------------------
# SERVICE ENVIRONMENT MODE (LOCAL vs DOCKER)
# -----------------------------
echo ""
echo "Where is backend service running?"
echo "  1) Dev (Local)"
echo "  2) Docker"
read -p "Enter choice (1/2): " ENV_MODE

if [[ "$ENV_MODE" == "1" ]]; then
  ENTITY_PATH="$OUTPUT_DIR/$PACKAGE_PATH_FORMATTED"
  UPDATED_ENTITY_PATH="$OUTPUT_DIR/updated_entity/$PACKAGE_PATH_FORMATTED"
  echo -e "${GREEN}✔ Local paths selected${NC}"

elif [[ "$ENV_MODE" == "2" ]]; then
  ENTITY_PATH="${DOCKER_ENTITY_PATH}/${PACKAGE_PATH_FORMATTED}"
  UPDATED_ENTITY_PATH="${DOCKER_ENTITY_PATH}/updated_entity/${PACKAGE_PATH_FORMATTED}"
  echo -e "${GREEN}✔ Docker paths set automatically${NC}"
  echo "  ENTITY_PATH: $ENTITY_PATH"
  echo "  UPDATED_ENTITY_PATH: $UPDATED_ENTITY_PATH"
else
  echo -e "${RED}✘ Invalid mode selected.${NC}"
  exit 1
fi

# Extract DB Host & Port safely from JDBC URL

CLEAN_URL=$(echo "$JDBC_URL" | sed -E \
  -e 's/^jdbc:[a-zA-Z]+(:thin)?:@?\/\///' \
  -e 's/^jdbc:[a-zA-Z]+:\/\///' \
  -e 's/^jdbc:[a-zA-Z]+:@//')

DB_HOST=$(echo "$CLEAN_URL" | sed -E 's/^([^:\/;]+).*/\1/')
DB_PORT=$(echo "$CLEAN_URL" | sed -E 's/^[^:]+:([0-9]+).*/\1/')

# Fallback if no port detected
if [[ "$DB_PORT" == "$CLEAN_URL" || "$DB_PORT" == "$DB_HOST" ]]; then
  DB_PORT=""
fi

# -----------------------------
#  CURL PAYLOAD
# -----------------------------
CURL_DATA=$(cat <<EOF
{
  "data": {
    "DB_CHILD_TABLE": "$CHILD_TABLES",
    "DB_READ_RECORD_${UPPER_STRATEGY}_INDICATOR": "$STRATEGY_INDICATOR",
    "CUSTOM_CONFIGURATION": "$CUSTOM_CONFIG",
    "STRATEGY": "$STRATEGY"
  },
  "tableName": "$TABLE_INPUT",
  "autoPopulate": $AUTO_POPULATE,
  "entityPath": "$ENTITY_PATH",
  "updatedEntityPath": "$UPDATED_ENTITY_PATH",
  "packagePath": "$PACKAGE_NAME",
  "dbInfo": {
    "SCHEMA_NAME": "$SCHEMA_NAME",
    "DB_HOST": "$DB_HOST",
    "DB_PORT": "$DB_PORT",
    "DB_DIALECT": "$DB_DIALECT",
    "DB_CONNECTION_URL": "$JDBC_URL",
    "DB_USER_NAME": "$DB_USER",
    "DB_USER_PASSWORD": "$DB_PASS",
    "DB_DRIVER_NAME": "$DB_DRIVER"
  }
}
EOF
)

echo ""
echo -e "${YELLOW}Generated CURL Command:${NC}"
echo "curl --location --request POST 'http://localhost:6002/cd/cli/update/entity/files' \\"
echo " --header 'Content-Type: application/json' \\"
echo " --data-raw '$CURL_DATA'"
echo ""

read -p "Execute CURL now? (y/n): " RUN_CURL

if [[ "$RUN_CURL" =~ ^[Yy]$ ]]; then
  echo -e "${CYAN}Executing CURL...${NC}"
  curl --location --request POST "http://localhost:6002/cd/cli/update/entity/files" \
    --header "Content-Type: application/json" \
    --data-raw "$CURL_DATA"
  echo -e "${GREEN}✔ CURL executed${NC}"
else
  echo -e "${YELLOW}⚠ CURL skipped${NC}"
fi

# ======================================================
#      PACKAGE UPDATED ENTITY FILES INTO JAR
# ======================================================
echo ""
echo -e "${CYAN}--------------------------------------------"
echo -e "           PACKAGE UPDATED ENTITY JAR"
echo -e "--------------------------------------------${NC}"

echo "Default packaging source: $OUTPUT_DIR/updated_entity/$PACKAGE_PATH_FORMATTED"
read -p "Enter packaging source path (or press ENTER for default): " PACK_SRC
PACK_SRC="${PACK_SRC:-$OUTPUT_DIR/updated_entity/$PACKAGE_PATH_FORMATTED}"

# ---- SANITIZE PACK_SRC ----
# remove any backslashes that were inserted (\/)
PACK_SRC="${PACK_SRC//\\//}"

# collapse multiple consecutive slashes to a single slash
PACK_SRC="$(echo "$PACK_SRC" | sed -E 's:/+:/:g')"

# remove any trailing slash (optional, so jar tool gets consistent input)
PACK_SRC="${PACK_SRC%/}"

echo ""
read -p "Enter output JAR path (absolute path with filename): " PACK_OUTPUT

# SANITIZE PACK_OUTPUT as well (in case user pasted escaped path)
PACK_OUTPUT="${PACK_OUTPUT//\\//}"
PACK_OUTPUT="$(echo "$PACK_OUTPUT" | sed -E 's:/+:/:g')"

echo ""
echo -e "${CYAN}Running Packager JAR...${NC}"
echo "java -jar \"$PACKAGER_JAR\" -s \"$PACK_SRC\" -o \"$PACK_OUTPUT\""
echo ""

java -jar "$PACKAGER_JAR" -s "$PACK_SRC" -o "$PACK_OUTPUT"

if [[ $? -ne 0 ]]; then
  echo -e "${RED}✘ Packaging failed.${NC}"
  exit 1
fi

echo -e "${GREEN}✔ Packaging completed successfully!${NC}"
