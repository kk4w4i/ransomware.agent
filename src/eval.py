import asyncio
import json
import os
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import requests
from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore

from src.managers.vector_store_manager import LocalEmbeddings

try:
    import tldextract
except Exception:
    tldextract = None

# Map ransomwarelive_field -> ransomwareAgent_field
FIELD_MAP = {
    "group": ("group", "ransomwareGroup"),
    "victim": ("victim", "victimCompany"),
    "domain": ("domain", "companyWebDomain"),
    "attack_date": ("attackdate", "attackDate"),
    "country": ("country", "countryOfCompany"),
    "description": ("description", "description"),
    "discovered": ("discovered", "discovered"),
    "industry": ("activity", "industry")
}

DEFAULT_EVAL_FIELDS = [
    "victim",
    "group",
    "domain",
    "country",
    "description",
    "industry"
]

ATTACK_DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d"
]
DISCOVERED_FORMATS = [
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d"
]


# (alpha2, [variants...])
_COUNTRY_DATA = [
    ("AD", ["AD", "Andorra", "Andorran", "Andorrane", "Principality of Andorra", "Principat d'Andorra"]),
    ("AE", ["AE", "Emirates", "Emirati", "Emirien", "Emirienne", "UAE", "United Arab Emirates"]),
    ("AF", ["AF", "Afganistan", "Afghan", "Afghane", "Afghanistan", "Islamic Republic of Afghanistan"]),
    ("AG", ["AG", "Antigua and Barbuda", "Antiguaise et barbudien", "Antiguaise et barbudienne", "Antiguan, Barbudan"]),
    ("AI", ["AI", "Anguilla", "Anguillan", "Anguillane", "Anguillian"]),
    ("AL", ["AL", "Albanais", "Albanaise", "Albania", "Albanian", "Republic of Albania", "Shqiperi", "Shqiperia", "Shqipnia"]),
    ("AM", ["AM", "Armenia", "Armenian", "Armenien", "Armenienne", "Hayastan", "Republic of Armenia"]),
    ("AO", ["AO", "Angola", "Angolais", "Angolaise", "Angolan", "Republic of Angola", "Republica de Angola", "publika de an'la"]),
    ("AQ", ["AQ", "Antarctica", "Antarcticain", "Antarcticaine", "Antarctican"]),
    ("AR", ["AR", "Argentin", "Argentina", "Argentine", "Argentine Republic", "Republica Argentina"]),
    ("AS", ["AS", "Amelika Samoa", "American Samoa", "American Samoan", "Amerika Samoa", "Samoa Amelika", "Samoan", "Samoane"]),
    ("AT", ["AT", "Austria", "Austrian", "Autrichien", "Autrichienne", "Oesterreich", "Osterreich", "Republic of Austria"]),
    ("AU", ["AU", "Australia", "Australian", "Australien", "Australienne", "Commonwealth of Australia"]),
    ("AW", ["AW", "Aruba", "Arubais", "Arubaise", "Aruban"]),
    ("AX", ["AX", "Aaland", "Ahvenanmaa", "Aland", "Aland Islands", "Alandais", "Alandaise", "Alandish"]),
    ("AZ", ["AZ", "Azerbaidjanais", "Azerbaidjanaise", "Azerbaijan", "Azerbaijani", "Azrbaycan Respublikas", "Republic of Azerbaijan"]),
    ("BA", ["BA", "Bosnia and Herzegovina", "Bosnia-Herzegovina", "Bosnian, Herzegovinian", "Bosnien", "Bosnienne"]),
    ("BB", ["BB", "Barbadian", "Barbadien", "Barbadienne", "Barbados"]),
    ("BD", ["BD", "Bangladais", "Bangladaise", "Bangladesh", "Bangladeshi", "Gonoprojatontri Bangladesh", "People's Republic of Bangladesh"]),
    ("BE", ["BE", "Belge", "Belgian", "Belgie", "Belgien", "Belgique", "Belgium", "Kingdom of Belgium", "Konigreich Belgien", "Koninkrijk Belgie", "Royaume de Belgique"]),
    ("BF", ["BF", "Burkina Faso", "Burkinabe", "Burkinabee"]),
    ("BG", ["BG", "Bulgare", "Bulgaria", "Bulgarian", "Republic of Bulgaria"]),
    ("BH", ["BH", "Bahrain", "Bahraini", "Bahreinien", "Bahreinienne", "Kingdom of Bahrain", "Mamlakat al-Bahrayn"]),
    ("BI", ["BI", "Burundais", "Burundaise", "Burundi", "Burundian", "Republic of Burundi", "Republika y'Uburundi", "Republique du Burundi"]),
    ("BJ", ["BJ", "Benin", "Beninese", "Beninois", "Beninoise", "Republic of Benin", "Republique du Benin"]),
    ("BL", ["BL", "Barthelomeen", "Barthelomeenne", "Collectivite de Saint-Barthelemy", "Collectivity of Saint Barthelemy", "Saint Barthelemy", "Saint Barthelemy Islander", "St. Barthelemy"]),
    ("BM", ["BM", "Bermuda", "Bermudian", "Bermudien", "Bermudienne", "Somers Isles", "The Bermudas", "The Islands of Bermuda"]),
    ("BN", ["BN", "Brunei", "Brunei Darussalam", "Bruneian", "Bruneien", "Bruneienne", "Nation of Brunei", "Nation of Brunei, Abode of Peace", "the Abode of Peace"]),
    ("BO", ["BO", "Bolivia", "Bolivia, Plurinational State of", "Bolivian", "Bolivien", "Bolivienne", "Buliwya", "Buliwya Mamallaqta", "Estado Plurinacional de Bolivia", "Plurinational State of Bolivia", "Teta Volivia", "Wuliwya", "Wuliwya Suyu"]),
    ("BQ", ["BES islands", "Bonaire, Sint Eustatius and Saba", "Caribbean Netherlands", "Dutch", "Neerlandais", "Neerlandaise"]),
    ("BR", ["BR", "Brasil", "Brazil", "Brazilian", "Bresilien", "Bresilienne", "Federative Republic of Brazil", "Republica Federativa do Brasil"]),
    ("BS", ["BS", "Bahamas", "Bahamian", "Bahamien", "Bahamienne", "Commonwealth of the Bahamas"]),
    ("BT", ["BT", "Bhoutanais", "Bhoutanaise", "Bhutan", "Bhutanese", "Kingdom of Bhutan"]),
    ("BV", ["BV", "Bouvet Island", "Bouvet-ya", "Bouvetya"]),
    ("BW", ["BW", "Botswana", "Botswanais", "Botswanaise", "Lefatshe la Botswana", "Motswana", "Republic of Botswana"]),
    ("BY", ["BY", "Belarus", "Belarusian", "Bielarus", "Bielorusse", "Republic of Belarus"]),
    ("BZ", ["BZ", "Belize", "Belizean", "Belizien", "Belizienne"]),
    ("CA", ["CA", "Canada", "Canadian", "Canadien", "Canadienne"]),
    ("CC", ["CC", "Cocos (Keeling) Islands", "Cocos Islander", "Cocos Islands", "Keeling Islands", "Territory of the Cocos (Keeling) Islands"]),
    ("CD", ["CD", "Congo, the Democratic Republic of the", "Congo-Kinshasa", "Congolais", "Congolaise", "Congolese", "DR Congo", "DRC", "Democratic Republic of the Congo"]),
    ("CF", ["CF", "Centrafricain", "Centrafricaine", "Central African", "Central African Republic", "Republique centrafricaine"]),
    ("CG", ["CG", "Congo", "Congo-Brazzaville", "Congolais", "Congolaise", "Congolese", "Republic of the Congo"]),
    ("CH", ["CH", "Schweiz", "Suisse", "Svizra", "Svizzera", "Swiss", "Swiss Confederation", "Switzerland"]),
    ("CI", ["CI", "Cote d'Ivoire", "Ivoirien", "Ivoirienne", "Ivorian", "Ivory Coast", "Republic of Cote d'Ivoire", "Republique de Cote d'Ivoire"]),
    ("CK", ["CK", "Cook Islands", "Cook Islander"]),
    ("CL", ["CL", "Chile", "Chilean", "Chilien", "Chilienne", "Republic of Chile"]),
    ("CM", ["Cameroon", "Cameroonian", "CM", "Republic of Cameroon", "Republique du Cameroun"]),
    ("CN", ["CN", "China", "Chinese", "People's Republic of China", "PR China", "Zhungguo"]),
    ("CO", ["CO", "Colombia", "Colombian", "Colombien", "Colombienne", "Republic of Colombia", "Republica de Colombia"]),
    ("CR", ["CR", "Costa Rica", "Costaricain", "Costaricaine", "Costa Rican", "Republic of Costa Rica"]),
    ("CU", ["CU", "Cuba", "Cuban", "Cubain", "Cubaine", "Republic of Cuba", "Republica de Cuba"]),
    ("CV", ["CV", "Cape Verde", "Cabo Verde", "Republic of Cabo Verde"]),
    ("CW", ["CW", "Curacao", "Country of Curacao"]),
    ("CX", ["CX", "Christmas Island", "Christmas Islander", "Territory of Christmas Island"]),
    ("CY", ["CY", "Cipriot", "Cipriote", "Ciprus", "Cyprus", "Cypre", "Republic of Cyprus"]),
    ("CZ", ["CZ", "Czech", "Czech Republic", "Czechia"]),
    ("DE", ["DE", "Deutschland", "Federal Republic of Germany", "Germany", "German"]),
    ("DJ", ["DJ", "Djibouti", "Djiboutian", "Djiboutien", "Djiboutienne", "Republic of Djibouti", "Republique de Djibouti"]),
    ("DK", ["DK", "Danemark", "Denmark", "Danish", "Dansk", "Danse"]),
    ("DM", ["DM", "Dominica", "Dominican", "Dominican Republic of Dominica", "Commonwealth of Dominica"]),
    ("DO", ["DO", "Dominican Republic", "Dominican", "Dominican Republic of the Caribbean", "Republica Dominicana"]),
    ("DZ", ["DZ", "Algeria", "Algerian", "Algerien", "Algerienne", "People's Democratic Republic of Algeria", "People's Democratic Republic of Algeria"]),
    ("EC", ["EC", "Ecuador", "Ecuadorian", "Ecuadorien", "Ecuadorienne", "Republic of Ecuador", "Republica del Ecuador"]),
    ("EE", ["EE", "Eesti", "Estonia", "Estonian", "Republic of Estonia"]),
    ("EG", ["EG", "Egypt", "Egyptian", "Egyptien", "Egyptienne", "Arab Republic of Egypt"]),
    ("EH", ["EH", "Sahara Occidental", "Saharan", "Western Sahara"]),
    ("ER", ["ER", "Eretria", "Eritrea", "Eritrean", "Erythree"]),
    ("ES", ["ES", "Espana", "Spain", "Spanish", "Kingdom of Spain"]),
    ("ET", ["ET", "Ethiopia", "Ethiopian", "Federal Democratic Republic of Ethiopia"]),
    ("FI", ["FI", "Finland", "Finn", "Finnish", "Finnish Republic", "Republic of Finland"]),
    ("FJ", ["FJ", "Fiji", "Fijian", "Fijien", "Fijienne", "Republic of Fiji"]),
    ("FK", ["Falkland Islands", "Malvinas", "Malvinas Islands", "FK"]),
    ("FM", ["FM", "Federated States of Micronesia", "Micronesia", "Micronesian"]),
    ("FO", ["FO", "Faroe Islands", "Faroese", "Faroese Islands"]),
    ("FR", ["FR", "France", "French", "Republique francaise"]),
    ("GA", ["GA", "Gabon", "Gabonais", "Gabonaise", "Gabonese", "Gabonese Republic", "Republic of Gabon"]),
    ("GB", ["Britannique", "British", "GB", "Great Britain", "UK", "United Kingdom", "United Kingdom of Great Britain and Northern Ireland"]),
    ("GD", ["GD", "Grenada", "Grenadan", "Grenadian", "Grenadien", "Grenadienne"]),
    ("GE", ["GE", "Georgia", "Georgian", "Sakartvelo"]),
    ("GF", ["French Guiana", "GF"]),
    ("GG", ["GG", "Guernsey", "Guernseyman", "Guernseywoman"]),
    ("GH", ["GH", "Ghana", "Ghanaian", "Ghanai", "Ghanais"]),
    ("GI", ["GI", "Gibraltar", "Gibraltarian"]),
    ("GL", ["GL", "Greenland", "Greenlandic", "Kalaallit Nunaat"]),
    ("GM", ["Gambia", "Gambian", "GM"]),
    ("GN", ["GN", "Guinea", "Guinean", "Guinean Republic", "Republic of Guinea"]),
    ("GP", ["GP", "Guadeloupe", "Guadeloupeen", "Guadeloupeenne"]),
    ("GQ", ["Equatorial Guinea", "GQ", "Equatoriale Guinee", "Equatorial Guinean"]),
    ("GR", ["GR", "Greece", "Greek", "Hellas", "Hellenic Republic"]),
    ("GS", ["GS", "South Georgia and the South Sandwich Islands"]),
    ("GT", ["GT", "Guatemala", "Guatemalan", "Guatemalteco", "Republic of Guatemala"]),
    ("GU", ["GU", "Guam", "Guamanian"]),
    ("GW", ["GW", "Guinea-Bissau", "Guinean", "Republica da Guine-Bissau"]),
    ("GY", ["GY", "Guyana", "Guyanese", "Republic of Guyana"]),
    ("HK", ["HK", "Hong Kong", "Hong Kong SAR China"]),
    ("HM", ["HM", "Heard Island and McDonald Islands"]),
    ("HN", ["HN", "Honduras", "Honduran", "Republic of Honduras", "Republica de Honduras"]),
    ("HR", ["Croatia", "Croatian", "HR"]),
    ("HT", ["HT", "Haiti", "Haitian", "Republique d'Haiti"]),
    ("HU", ["HU", "Hungary", "Hungarian", "Magyarorszag"]),
    ("ID", ["ID", "Indonesia", "Indonesian", "Republic of Indonesia"]),
    ("IE", ["IE", "Ireland", "Irish", "Republic of Ireland"]),
    ("IL", ["IL", "Israel", "Israeli", "State of Israel"]),
    ("IM", ["IM", "Isle of Man", "Manx", "Mann"]),
    ("IN", ["IN", "India", "Indian", "Republic of India"]),
    ("IO", ["British Indian Ocean Territory", "IO", "Chagos Archipelago"]),
    ("IQ", ["IQ", "Iraq", "Iraqi", "Republic of Iraq"]),
    ("IR", ["Iran", "Iran (Islamic Republic of)", "Ira", "IR", "Islamic Republic of Iran"]),
    ("IS", ["IS", "Iceland", "Icelandic", "Republic of Iceland"]),
    ("IT", ["IT", "Italia", "Italian Republic", "Italy"]),
    ("JE", ["JE", "Jersey", "Jerseyman", "Jerseywoman"]),
    ("JM", ["JM", "Jamaica", "Jamaican"]),
    ("JO", ["Hashemite Kingdom of Jordan", "Jordan", "Jordanian", "JO"]),
    ("JP", ["JP", "Japan", "Japanese", "Nihon", "Nippon"]),
    ("KE", ["KE", "Kenya", "Kenyan", "Republic of Kenya"]),
    ("KG", ["Kyrgyz Republic", "Kyrgyzstan", "Kyrgyzstani", "KG"]),
    ("KH", ["Cambodia", "Cambodian", "KH", "Khmer", "Kingdom of Cambodia"]),
    ("KI", ["KI", "Kiribati", "Kiribatian", "Republic of Kiribati"]),
    ("KM", ["Comoros", "Comorian", "KM", "Union of the Comoros"]),
    ("KN", ["KN", "Saint Kitts and Nevis", "Saint Kitts and Nevisian", "St. Kitts and Nevis"]),
    ("KP", ["Democratic People's Republic of Korea", "DPR Korea", "KP", "North Korea", "North Korean"]),
    ("KR", ["KR", "Republic of Korea", "South Korea", "South Korean"]),
    ("KW", ["KW", "Kuwait", "Kuwaiti", "State of Kuwait"]),
    ("KY", ["KY", "Cayman Islands", "Caymanian"]),
    ("KZ", ["KZ", "Kazakhstan", "Kazakh", "Kazakhstani", "Republic of Kazakhstan"]),
    ("LA", ["LA", "Lao People's Democratic Republic", "Laos", "Lao", "Lao People's Democratic Republic"]),
    ("LB", ["LB", "Lebanese Republic", "Lebanon", "Lebanese"]),
    ("LC", ["LC", "Saint Lucia", "Saint Lucian"]),
    ("LI", ["LI", "Liechtenstein", "Liechtensteiner", "Principality of Liechtenstein"]),
    ("LK", ["LK", "Sri Lanka", "Sri Lankan", "Democratic Socialist Republic of Sri Lanka"]),
    ("LR", ["LR", "Liberia", "Liberian", "Republic of Liberia"]),
    ("LS", ["Kingdom of Lesotho", "Lesotho", "Lesothan", "Lesothoan", "Lesothonian", "Lesothon"]),
    ("LT", ["LT", "Lithuania", "Lithuanian", "Republic of Lithuania"]),
    ("LU", ["Grand Duchy of Luxembourg", "Grand-Duche de Luxembourg", "Luxembourg", "Luxembourgish", "LU"]),
    ("LV", ["LV", "Latvia", "Latvian", "Republic of Latvia"]),
    ("LY", ["LY", "Libya", "Libyan", "State of Libya"]),
    ("MA", ["Kingdom of Morocco", "MA", "Morocco", "Moroccan", "Royaume du Maroc"]),
    ("MC", ["MC", "Monaco", "Monegasque", "Principality of Monaco"]),
    ("MD", ["MD", "Republic of Moldova", "Moldova", "Moldovan"]),
    ("ME", ["ME", "Montenegro", "Montenegrin", "Crna Gora"]),
    ("MF", ["Collectivite de Saint-Martin", "Saint Martin", "Saint Martin (French part)", "MF"]),
    ("MG", ["MG", "Madagascar", "Malagasy", "Republic of Madagascar", "Republique de Madagascar"]),
    ("MH", ["Marshall Islands", "MH", "Marshallese"]),
    ("MK", ["MK", "North Macedonia", "Republic of North Macedonia"]),
    ("ML", ["ML", "Mali", "Malian", "Republic of Mali"]),
    ("MM", ["Burma", "MM", "Myanmar", "Republic of the Union of Myanmar"]),
    ("MN", ["MN", "Mongolia", "Mongolian"]),
    ("MO", ["Macau", "Macao", "MO", "Macao Special Administrative Region of the People's Republic of China"]),
    ("MP", ["Commonwealth of the Northern Mariana Islands", "Northern Mariana Islands", "MP"]),
    ("MQ", ["Department of Martinique", "Martinique", "MQ"]),
    ("MR", ["Islamic Republic of Mauritania", "Mauritania", "Mauritanian", "MR"]),
    ("MS", ["MS", "Montserrat", "Montserratian"]),
    ("MT", ["Malta", "Maltese", "MT", "Republic of Malta"]),
    ("MU", ["MU", "Mauritius", "Mauritian", "Republic of Mauritius"]),
    ("MV", ["MV", "Maldives", "Maldivian", "Republic of Maldives"]),
    ("MW", ["Malawi", "Malawian", "Republic of Malawi", "MW"]),
    ("MX", ["Estados Unidos Mexicanos", "Mexico", "Mexican", "MX"]),
    ("MY", ["Federation of Malaysia", "Malaysia", "Malaysian", "MY"]),
    ("MZ", ["Mocambique", "Mozambique", "Mozambican", "Republic of Mozambique", "MZ"]),
    ("NA", ["NA", "Namibia", "Namibian", "Republic of Namibia"]),
    ("NC", ["NC", "New Caledonia", "New Caledonian"]),
    ("NE", ["NE", "Niger", "Nigerien", "Nigerienne", "Republic of the Niger", "Republique du Niger"]),
    ("NF", ["NF", "Norfolk Island", "Norfolk Islander"]),
    ("NG", ["Federal Republic of Nigeria", "NG", "Nigeria", "Nigerian"]),
    ("NI", ["NI", "Nicaragua", "Nicaraguan", "Republic of Nicaragua", "Republica de Nicaragua"]),
    ("NL", ["Holland", "Kingdom of the Netherlands", "Netherlands", "Dutch", "NL"]),
    ("NO", ["Kingdom of Norway", "NO", "Norway", "Norwegian"]),
    ("NP", ["Federal Democratic Republic of Nepal", "Nepal", "Nepalese", "NP"]),
    ("NR", ["NR", "Nauru", "Nauruan", "Republic of Nauru"]),
    ("NU", ["NU", "Niue", "Niuean"]),
    ("NZ", ["NZ", "New Zealand", "New Zealander", "Aotearoa"]),
    ("OM", ["OM", "Oman", "Omani", "Sultanate of Oman"]),
    ("PA", ["PA", "Panama", "Panamanian", "Republic of Panama", "Republica de Panama"]),
    ("PE", ["PE", "Peru", "Peruvian", "Republic of Peru", "Republica del Peru"]),
    ("PF", ["French Polynesia", "PF", "Polynesie francaise"]),
    ("PG", ["Independent State of Papua New Guinea", "Papua New Guinea", "Papua New Guinean", "PG"]),
    ("PH", ["PH", "Philippines", "Philippine", "Pilipinas", "Republic of the Philippines"]),
    ("PK", ["Islamic Republic of Pakistan", "Pakistan", "Pakistani", "PK"]),
    ("PL", ["PL", "Poland", "Poland Republic", "Polish", "Republic of Poland"]),
    ("PM", ["PM", "Saint Pierre and Miquelon", "Saint-Pierrais", "Saint-Pierraise"]),
    ("PN", ["Pitcairn", "Pitcairn Islands", "PN"]),
    ("PR", ["Commonwealth of Puerto Rico", "Puerto Rico", "Puerto Rican", "PR"]),
    ("PS", ["Palestine", "Palestine, State of", "Palestinian", "PS", "State of Palestine"]),
    ("PT", ["PT", "Portugal", "Portuguese", "Republica Portuguesa"]),
    ("PW", ["PW", "Palau", "Palauan", "Republic of Palau"]),
    ("PY", ["PY", "Paraguay", "Paraguayan", "Republic of Paraguay", "Republica del Paraguay"]),
    ("QA", ["QA", "Qatar", "Qatari", "State of Qatar"]),
    ("RE", ["RE", "Reunion", "Reunionese", "Reunionnais", "Reunionnaise"]),
    ("RO", ["RO", "Romania", "Romanian", "Romanian Republic"]),
    ("RS", ["Republic of Serbia", "Serbia", "Serbian", "RS"]),
    ("RU", ["Rus Federation", "Russia", "Russian Federation", "Russian", "RU"]),
    ("RW", ["Republic of Rwanda", "Rwanda", "Rwandan", "RW"]),
    ("SA", ["Kingdom of Saudi Arabia", "Saudi Arabia", "Saudi", "SA"]),
    ("SB", ["SB", "Solomon Islands", "Solomon Islander"]),
    ("SC", ["Republic of Seychelles", "Seychelles", "Seychellois", "SC"]),
    ("SD", ["Republic of the Sudan", "Sudan", "Sudanese", "SD"]),
    ("SE", ["Kingdom of Sweden", "SE", "Sweden", "Swedish"]),
    ("SG", ["Republic of Singapore", "Singapore", "Singaporean", "SG"]),
    ("SH", ["Saint Helena, Ascension and Tristan da Cunha", "Saint Helenian", "SH"]),
    ("SI", ["Republic of Slovenia", "Slovenia", "Slovene", "Slovenian", "SI"]),
    ("SJ", ["Svalbard and Jan Mayen", "SJ"]),
    ("SK", ["SK", "Slovak", "Slovakia", "Slovak Republic"]),
    ("SL", ["Republic of Sierra Leone", "Sierra Leone", "Sierra Leonean", "SL"]),
    ("SM", ["Republic of San Marino", "San Marino", "Sammarinese", "SM"]),
    ("SN", ["Republic of Senegal", "Senegal", "Senegalese", "SN"]),
    ("SO", ["Federal Republic of Somalia", "Somalia", "Somali", "Somalian", "SO"]),
    ("SR", ["Republic of Suriname", "Suriname", "Surinamese", "SR"]),
    ("SS", ["Republic of South Sudan", "South Sudan", "South Sudanese", "SS"]),
    ("ST", ["Democratic Republic of Sao Tome and Principe", "Sao Tome and Principe", "Sao Tomean", "ST", "Santomeen", "Santomeenne"]),
    ("SV", ["El Salvador", "Republic of El Salvador", "Republica de El Salvador", "SV", "Salvadoran", "Salvadorien", "Salvadorienne"]),
    ("SX", ["SX", "Saint-Martinois", "Saint-Martinoise", "Sint Maarten", "Sint Maarten (Dutch part)", "St. Maartener"]),
    ("SY", ["Al-Jumhuriyah Al-Arabiyah As-Suriyah", "SY", "Syria", "Syrian", "Syrian Arab Republic", "Syrien", "Syrienne"]),
    ("SZ", ["Eswatini", "Kingdom of Eswatini", "Ngwane", "SZ", "Swatini", "Swazi", "Swazie", "Swaziland", "Umbuso weSwatini", "weSwatini"]),
    ("TC", ["TC", "Turks and Caicos Islander", "Turks and Caicos Islands"]),
    ("TD", ["Chad", "Chadian", "Republic of Chad", "Republique du Tchad", "TD", "Tchad", "Tchadien", "Tchadienne"]),
    ("TF", ["Francais", "Francaise", "French", "French Southern Territories", "French Southern and Antarctic Lands", "TF", "Territory of the French Southern and Antarctic Lands"]),
    ("TG", ["Republique Togolaise", "TG", "Togo", "Togolais", "Togolaise", "Togolese", "Togolese Republic"]),
    ("TH", ["Kingdom of Thailand", "Prathet", "Ratcha Anachak Thai", "TH", "Thai", "Thailand", "Thailandais", "Thailandaise"]),
    ("TJ", ["Cumhuriyi Tocikiston", "Republic of Tajikistan", "TJ", "Tadjike", "Tadzhik", "Tajikistan", "Tocikiston"]),
    ("TK", ["TK", "Tokelau", "Tokelauan"]),
    ("TL", ["Democratic Republic of Timor-Leste", "East Timor", "East Timorese", "Est-timorais", "Est-timoraise", "Republica Democratica de Timor-Leste", "Republika Demokratika Timor-Leste", "TL", "Timor Lorosa'e", "Timor Lorosae", "Timor-Leste"]),
    ("TM", ["TM", "Turkmen", "Turkmene", "Turkmenistan"]),
    ("TN", ["Republic of Tunisia", "TN", "Tunisia", "Tunisian", "Tunisian Republic", "Tunisien", "Tunisienne", "al-Jumhuriyyah at-Tunisiyyah"]),
    ("TO", ["Kingdom of Tonga", "TO", "Tonga", "Tongan", "Tonguien", "Tonguienne"]),
    ("TR", ["Republic of Turkey", "TR", "Turc", "Turkey", "Turkish", "Turkiye", "Turkiye Cumhuriyeti", "Turque"]),
    ("TT", ["Republic of Trinidad and Tobago", "TT", "Trinidad and Tobago", "Trinidadian", "Trinidadien", "Trinidadienne"]),
    ("TV", ["TV", "Tuvalu", "Tuvaluan", "Tuvaluane"]),
    ("TW", ["Chinese Taipei", "Republic of China", "Republic of China (Taiwan)", "TW", "Taiwan", "Taiwanais", "Taiwanaise", "Taiwanese", "Zhonghua Minguo"]),
    ("TZ", ["Jamhuri ya Muungano wa Tanzania", "TZ", "Tanzania", "Tanzania, United Republic of", "Tanzanian", "Tanzanien", "Tanzanienne", "United Republic of Tanzania"]),
    ("UA", ["UA", "Ukraine", "Ukrainian", "Ukrainien", "Ukrainienne", "Ukrayina"]),
    ("UG", ["Jamhuri ya Uganda", "Ougandais", "Ougandaise", "Republic of Uganda", "UG", "Uganda", "Ugandan"]),
    ("UM", ["American Islander", "UM", "United States Minor Outlying Islands"]),
    ("US", ["Americain", "Americaine", "American", "US", "USA", "United States", "United States of America"]),
    ("UY", ["Oriental Republic of Uruguay", "Republica Oriental del Uruguay", "UY", "Uruguay", "Uruguayan", "Uruguayen", "Uruguayenne"]),
    ("UZ", ["Ouzbeke", "Ozbekiston Respublikasi", "Republic of Uzbekistan", "UZ", "Uzbekistan", "Uzbekistani"]),
    ("VA", ["Holy See (Vatican City State)", "Stato della Citta del Vaticano", "VA", "Vatican", "Vatican City", "Vatican City State", "Vaticane"]),
    ("VC", ["Saint Vincent and the Grenadines", "Saint Vincentian", "VC", "Vincentais", "Vincentaise"]),
    ("VE", ["Bolivarian Republic of Venezuela", "Republica Bolivariana de Venezuela", "VE", "Venezuela", "Venezuela, Bolivarian Republic of", "Venezuelan", "Venezuelien", "Venezuelienne"]),
    ("VG", ["British Virgin Islands", "VG", "Virgin Islander", "Virgin Islands", "Virgin Islands, British"]),
    ("VI", ["United States Virgin Islands", "VI", "Virgin Islander", "Virgin Islands of the United States", "Virgin Islands, U.S."]),
    ("VN", ["Cong hoa Xa hoi chu nghia Viet Nam", "Socialist Republic of Vietnam", "VN", "Viet Nam", "Vietnam", "Vietnamese", "Vietnamien", "Vietnamienne"]),
    ("VU", ["Ni-Vanuatu", "Republic of Vanuatu", "Republique de Vanuatu", "Ripablik blong Vanuatu", "VU", "Vanuatu", "Vanuatuan", "Vanuatuane"]),
    ("WF", ["Territoire des iles Wallis et Futuna", "Territory of the Wallis and Futuna Islands", "WF", "Wallis and Futuna", "Wallis and Futuna Islander"]),
    ("WS", ["Independent State of Samoa", "Malo Saoloto Tutoatasi o Samoa", "Samoa", "Samoan", "Samoane", "WS"]),
    ("XK", ["Kosovar", "Kosovare", "Kosovo", "Republic of Kosovo", "XK"]),
    ("YE", ["Republic of Yemen", "YE", "Yemen", "Yemeni", "Yemeni Republic", "Yemenite", "al-Jumhuriyyah al-Yamaniyyah"]),
    ("YT", ["Departement de Mayotte", "Department of Mayotte", "Mahorais", "Mahoraise", "Mahoran", "Mayotte", "YT"]),
    ("ZA", ["RSA", "Republic of South Africa", "South Africa", "South African", "Sud-africain", "Sud-africaine", "Suid-Afrika", "ZA"]),
    ("ZM", ["Republic of Zambia", "ZM", "Zambia", "Zambian", "Zambien", "Zambienne"]),
    ("ZW", ["Republic of Zimbabwe", "ZW", "Zimbabwe", "Zimbabwean", "Zimbabween", "Zimbabweenne"])
]


def _country_key(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(ch for ch in ascii_value if not unicodedata.combining(ch))
    ascii_value = ascii_value.replace("&", " and ")
    ascii_value = ascii_value.lower()
    ascii_value = re.sub(r"[^a-z0-9]+", " ", ascii_value)
    return ascii_value.strip()


_COUNTRY_ALPHA3_TO_ALPHA2 = {
    "AFG": "AF",
    "ALA": "AX",
    "ALB": "AL",
    "AND": "AD",
    "ARE": "AE",
    "ARG": "AR",
    "ARM": "AM",
    "ASM": "AS",
    "ATA": "AQ",
    "ATF": "TF",
    "ATG": "AG",
    "AUS": "AU",
    "AUT": "AT",
    "AZE": "AZ",
    "BDI": "BI",
    "BEL": "BE",
    "BEN": "BJ",
    "BES": "BQ",
    "BFA": "BF",
    "BGD": "BD",
    "BGR": "BG",
    "BHR": "BH",
    "BHS": "BS",
    "BIH": "BA",
    "BLM": "BL",
    "BLR": "BY",
    "BLZ": "BZ",
    "BMU": "BM",
    "BOL": "BO",
    "BRA": "BR",
    "BRB": "BB",
    "BRN": "BN",
    "BTN": "BT",
    "BVT": "BV",
    "BWA": "BW",
    "CAF": "CF",
    "CAN": "CA",
    "CCK": "CC",
    "CHE": "CH",
    "CHL": "CL",
    "CHN": "CN",
    "CIV": "CI",
    "CMR": "CM",
    "COD": "CD",
    "COG": "CG",
    "COK": "CK",
    "COL": "CO",
    "COM": "KM",
    "CPV": "CV",
    "CRI": "CR",
    "CUB": "CU",
    "CUW": "CW",
    "CXR": "CX",
    "CYM": "KY",
    "CYP": "CY",
    "CZE": "CZ",
    "DEU": "DE",
    "DJI": "DJ",
    "DMA": "DM",
    "DNK": "DK",
    "DOM": "DO",
    "DZA": "DZ",
    "ECU": "EC",
    "EGY": "EG",
    "ERI": "ER",
    "ESH": "EH",
    "ESP": "ES",
    "EST": "EE",
    "ETH": "ET",
    "FIN": "FI",
    "FJI": "FJ",
    "FLK": "FK",
    "FRA": "FR",
    "FRO": "FO",
    "FSM": "FM",
    "GAB": "GA",
    "GBR": "GB",
    "GEO": "GE",
    "GGY": "GG",
    "GHA": "GH",
    "GIB": "GI",
    "GIN": "GN",
    "GLP": "GP",
    "GMB": "GM",
    "GNB": "GW",
    "GNQ": "GQ",
    "GRC": "GR",
    "GRD": "GD",
    "GRL": "GL",
    "GTM": "GT",
    "GUF": "GF",
    "GUM": "GU",
    "GUY": "GY",
    "HKG": "HK",
    "HMD": "HM",
    "HND": "HN",
    "HRV": "HR",
    "HTI": "HT",
    "HUN": "HU",
    "IDN": "ID",
    "IMN": "IM",
    "IND": "IN",
    "IOT": "IO",
    "IRL": "IE",
    "IRN": "IR",
    "IRQ": "IQ",
    "ISL": "IS",
    "ISR": "IL",
    "ITA": "IT",
    "JAM": "JM",
    "JEY": "JE",
    "JOR": "JO",
    "JPN": "JP",
    "KAZ": "KZ",
    "KEN": "KE",
    "KGZ": "KG",
    "KHM": "KH",
    "KIR": "KI",
    "KNA": "KN",
    "KOR": "KR",
    "KWT": "KW",
    "LAO": "LA",
    "LBN": "LB",
    "LBR": "LR",
    "LBY": "LY",
    "LCA": "LC",
    "LIE": "LI",
    "LKA": "LK",
    "LSO": "LS",
    "LTU": "LT",
    "LUX": "LU",
    "LVA": "LV",
    "MAC": "MO",
    "MAF": "MF",
    "MAR": "MA",
    "MCO": "MC",
    "MDA": "MD",
    "MDG": "MG",
    "MDV": "MV",
    "MEX": "MX",
    "MHL": "MH",
    "MKD": "MK",
    "MLI": "ML",
    "MLT": "MT",
    "MMR": "MM",
    "MNE": "ME",
    "MNG": "MN",
    "MNP": "MP",
    "MOZ": "MZ",
    "MRT": "MR",
    "MSR": "MS",
    "MTQ": "MQ",
    "MUS": "MU",
    "MWI": "MW",
    "MYS": "MY",
    "MYT": "YT",
    "NAM": "NA",
    "NCL": "NC",
    "NER": "NE",
    "NFK": "NF",
    "NGA": "NG",
    "NIC": "NI",
    "NIU": "NU",
    "NLD": "NL",
    "NOR": "NO",
    "NPL": "NP",
    "NRU": "NR",
    "NZL": "NZ",
    "OMN": "OM",
    "PAK": "PK",
    "PAN": "PA",
    "PCN": "PN",
    "PER": "PE",
    "PHL": "PH",
    "PLW": "PW",
    "PNG": "PG",
    "POL": "PL",
    "PRI": "PR",
    "PRK": "KP",
    "PRT": "PT",
    "PRY": "PY",
    "PSE": "PS",
    "PYF": "PF",
    "QAT": "QA",
    "REU": "RE",
    "ROU": "RO",
    "RUS": "RU",
    "RWA": "RW",
    "SAU": "SA",
    "SDN": "SD",
    "SEN": "SN",
    "SGP": "SG",
    "SGS": "GS",
    "SHN": "SH",
    "SJM": "SJ",
    "SLB": "SB",
    "SLE": "SL",
    "SLV": "SV",
    "SMR": "SM",
    "SOM": "SO",
    "SPM": "PM",
    "SRB": "RS",
    "SSD": "SS",
    "STP": "ST",
    "SUR": "SR",
    "SVK": "SK",
    "SVN": "SI",
    "SWE": "SE",
    "SWZ": "SZ",
    "SXM": "SX",
    "SYR": "SY",
    "TCA": "TC",
    "TCD": "TD",
    "TGO": "TG",
    "THA": "TH",
    "TJK": "TJ",
    "TKL": "TK",
    "TKM": "TM",
    "TLS": "TL",
    "TON": "TO",
    "TTO": "TT",
    "TUN": "TN",
    "TUR": "TR",
    "TUV": "TV",
    "TWN": "TW",
    "TZA": "TZ",
    "UGA": "UG",
    "UKR": "UA",
    "UMI": "UM",
    "UNK": "XK",
    "URY": "UY",
    "USA": "US",
    "UZB": "UZ",
    "VAT": "VA",
    "VCT": "VC",
    "VEN": "VE",
    "VGB": "VG",
    "VIR": "VI",
    "VNM": "VN",
    "VUT": "VU",
    "WLF": "WF",
    "WSM": "WS",
    "YEM": "YE",
    "ZAF": "ZA",
    "ZMB": "ZM",
    "ZWE": "ZW",
}


_COUNTRY_CODE_SET = {code for code, _ in _COUNTRY_DATA}
_COUNTRY_LOOKUP: Dict[str, str] = {}

for code, variants in _COUNTRY_DATA:
    code_upper = code.upper()
    _COUNTRY_CODE_SET.add(code_upper)

    for variant in [code_upper, code_upper.lower(), *variants]:
        key = _country_key(variant)
        if key:
            _COUNTRY_LOOKUP.setdefault(key, code_upper)
            _COUNTRY_LOOKUP.setdefault(key.replace(" ", ""), code_upper)

for alpha3, alpha2 in _COUNTRY_ALPHA3_TO_ALPHA2.items():
    key = _country_key(alpha3)
    _COUNTRY_LOOKUP.setdefault(key, alpha2)
    _COUNTRY_LOOKUP.setdefault(alpha3.lower(), alpha2)

_COUNTRY_ADDITIONAL_ALIASES = {
    "bahamas": "BS",
    "bolivia": "BO",
    "britain": "GB",
    "brunei": "BN",
    "cape verde": "CV",
    "caribbean netherlands": "BQ",
    "china mainland": "CN",
    "congo": "CG",
    "democratic republic of congo": "CD",
    "democratic republic of the congo": "CD",
    "england": "GB",
    "gambia": "GM",
    "great britain": "GB",
    "holy see": "VA",
    "hong kong": "HK",
    "iran": "IR",
    "ivory coast": "CI",
    "kosovo": "XK",
    "laos": "LA",
    "macau": "MO",
    "micronesia": "FM",
    "moldova": "MD",
    "myanmar": "MM",
    "north korea": "KP",
    "palestine": "PS",
    "russia": "RU",
    "south korea": "KR",
    "south sudan": "SS",
    "swaziland": "SZ",
    "syria": "SY",
    "taiwan": "TW",
    "tanzania": "TZ",
    "turkiye": "TR",
    "u.s.": "US",
    "uae": "AE",
    "united kingdom": "GB",
    "united states": "US",
    "united states of america": "US",
    "venezuela": "VE",
    "vietnam": "VN",
    "virgin islands": "VG",
}

for alias, code in _COUNTRY_ADDITIONAL_ALIASES.items():
    key = _country_key(alias)
    if key:
        _COUNTRY_LOOKUP[key] = code
        _COUNTRY_LOOKUP[key.replace(" ", "")] = code


_embedder: Optional[LocalEmbeddings] = None
_embedding_cache: Dict[str, np.ndarray] = {}


def _get_embedder() -> LocalEmbeddings:
    global _embedder
    if _embedder is None:
        _embedder = LocalEmbeddings()
    return _embedder


def _get_embedding(text: Optional[str]) -> Optional[np.ndarray]:
    if not text:
        return None
    key = text.strip().lower()
    cached = _embedding_cache.get(key)
    if cached is not None:
        return cached

    embedder = _get_embedder()
    try:
        embedding = np.array(embedder.generate_embedding(text), dtype=np.float32)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Embedding generation failed: {exc}")
        return None

    _embedding_cache[key] = embedding
    return embedding


def _cosine_similarity(vec_a: Optional[np.ndarray], vec_b: Optional[np.ndarray]) -> float:
    if vec_a is None and vec_b is None:
        return 1.0
    if vec_a is None or vec_b is None:
        return 0.0
    denom = float(np.linalg.norm(vec_a) * np.linalg.norm(vec_b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / denom)


def _vector_similarity(a: Optional[str], b: Optional[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    emb_a = _get_embedding(a)
    emb_b = _get_embedding(b)
    return _cosine_similarity(emb_a, emb_b)

def _parse_dt(s: Optional[str], formats):
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None

def _normalize_country_code(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = value.strip() if isinstance(value, str) else str(value).strip()
    if not text:
        return None

    ascii_text = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(ch for ch in ascii_text if not unicodedata.combining(ch))
    ascii_text = ascii_text.strip()

    candidate = re.sub(r"[^A-Z]", "", ascii_text.upper())
    if len(candidate) == 2 and candidate in _COUNTRY_CODE_SET:
        return candidate
    if len(candidate) == 3:
        mapped = _COUNTRY_ALPHA3_TO_ALPHA2.get(candidate)
        if mapped:
            return mapped

    key = _country_key(ascii_text)
    if key:
        code = _COUNTRY_LOOKUP.get(key)
        if code:
            return code
        code = _COUNTRY_LOOKUP.get(key.replace(" ", ""))
        if code:
            return code

    key = _country_key(text)
    if key:
        code = _COUNTRY_LOOKUP.get(key)
        if code:
            return code
        code = _COUNTRY_LOOKUP.get(key.replace(" ", ""))
        if code:
            return code

    return None


def _norm_text(x: Any) -> Optional[str]:
    if x is None:
        return None
    if not isinstance(x, str):
        return str(x)
    s = x.strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

def _norm_domain(x: Any) -> Optional[str]:
    s = _norm_text(x)
    if not s:
        return None
    s = re.sub(r"^[a-z]+://", "", s)
    s = s.split("/")[0]
    s = s.split(":")[0]
    if tldextract:
        ext = tldextract.extract(s)
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}"
        if ext.domain:
            return ext.domain
    return s[4:] if s.startswith("www.") else s

def _soft_ratio(a: Optional[str], b: Optional[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()

def _date_equal_by_day(a: Optional[datetime], b: Optional[datetime]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return 1.0 if (a.date() == b.date()) else 0.0

def extract_company_names(docs: List[Dict[str, Any]], key: str) -> set:
    return set(_norm_text(d[key]) for d in docs if key in d and d[key] not in (None, "", []))

async def eval_group(
    group_name: str,
    live_db_name: str,
    agent_db_name: str,
    live_coll_name: str,
    agent_coll_name: str,
    mongo_uri_env: str = "MONGODB_URI",
    fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Evaluate agent vs ransomware.live for a given group, with schema-aware normalization.
    Does global evaluation for all victimCompany values and per-victim company field comparison.
    """
    uri = os.getenv(mongo_uri_env)
    client = AsyncIOMotorClient(uri)

    live_coll = client[live_db_name][live_coll_name]
    agent_coll = client[agent_db_name][agent_coll_name]

    await import_group_victims(group_name, live_coll)

    live_group_name = await _best_group_name(group_name, live_coll, "group")
    agent_group_name = await _best_group_name(group_name, agent_coll, "ransomwareGroup")

    live_docs = await live_coll.find({
        "group": {"$regex": f"^{re.escape(live_group_name)}$", "$options": "i"}
    }).to_list(length=10000)
    agent_docs = await agent_coll.find({
        "ransomwareGroup": {"$regex": f"^{re.escape(agent_group_name)}$", "$options": "i"}
    }).to_list(length=10000)

    live_victim_map: Dict[str, Dict[str, Any]] = {}
    live_victim_profiles: List[Tuple[str, Optional[np.ndarray], Dict[str, Any]]] = []
    for live_doc in live_docs:
        live_name = _norm_text(live_doc.get("victim"))
        if not live_name:
            continue
        if live_name not in live_victim_map:
            live_victim_map[live_name] = live_doc
        live_victim_profiles.append((live_name, _get_embedding(live_name), live_doc))

    result = {
        "groupRequested": group_name,
        "groupMatched": {
            "live": live_group_name,
            "agent": agent_group_name,
        },
        "counts": {"live_docs": len(live_docs), "agent_docs": len(agent_docs)},
    }

    selected_fields: List[str]
    if isinstance(fields, str):
        selected_fields = [fields]
    else:
        selected_fields = list(fields) if fields else DEFAULT_EVAL_FIELDS

    allowed_fields = [f for f in selected_fields if f in FIELD_MAP]
    if not allowed_fields:
        allowed_fields = list(DEFAULT_EVAL_FIELDS)

    # --- Per victimCompany in agent collection: per-field eval ---
    detailed_per_victim = []
    unmatched_victims = []
    all_exact_scores = []
    all_soft_scores = []
    all_vector_scores = []
    field_scores = {}  # Track scores by field

    for agent_doc in agent_docs:
        agent_company = _norm_text(agent_doc.get("victimCompany"))
        if not agent_company:
            continue
        
        live_doc = live_victim_map.get(agent_company)
        match_type = "exact" if live_doc else "vector"
        best_vector_score = 0.0

        if live_doc is None:
            agent_embedding = _get_embedding(agent_company)
            if agent_embedding is None:
                unmatched_victims.append(agent_company)
                continue

            best_match_doc = None
            best_vector_score = -1.0
            for live_name, live_embedding, candidate_doc in live_victim_profiles:
                if live_embedding is None:
                    continue
                score = _cosine_similarity(agent_embedding, live_embedding)
                if score > best_vector_score:
                    best_vector_score = score
                    best_match_doc = candidate_doc

            if best_match_doc is None:
                unmatched_victims.append(agent_company)
                continue

            live_doc = best_match_doc

        victim_vector_score = _vector_similarity(
            agent_company,
            _norm_text(live_doc.get("victim")),
        )

        per_field_victim, exacts_victim, softs_victim, vectors_victim = [], [], [], []
        
        for canon in allowed_fields:
            live_k, agent_k = FIELD_MAP[canon]
            live_val = live_doc.get(live_k)
            agent_val = agent_doc.get(agent_k)
            
            if canon == "country":
                live_code = _normalize_country_code(live_val)
                agent_code = _normalize_country_code(agent_val)
                if live_code or agent_code:
                    exact = 1.0 if (live_code and agent_code and live_code == agent_code) else 0.0
                    soft = _soft_ratio(live_code, agent_code)
                    vector = _vector_similarity(live_code, agent_code)
                else:
                    ln = _norm_text(live_val)
                    an = _norm_text(agent_val)
                    exact = 1.0 if (ln and an and ln == an) else 0.0
                    soft = _soft_ratio(ln, an)
                    vector = _vector_similarity(ln, an)
            elif canon in ["victim", "group", "description", "industry", "domain"]:
                ln = _norm_text(live_val)
                an = _norm_text(agent_val)
                exact = 1.0 if (ln and an and ln == an) else 0.0
                soft = _soft_ratio(ln, an)
                vector = _vector_similarity(ln, an)
            elif canon in ("attack_date", "discovered"):
                if canon == "attack_date":
                    ld_val = _parse_dt(live_val, ATTACK_DATE_FORMATS)
                    ad_val = _parse_dt(agent_val, ATTACK_DATE_FORMATS)
                else:
                    ld_val = _parse_dt(live_val, DISCOVERED_FORMATS)
                    ad_val = _parse_dt(agent_val, DISCOVERED_FORMATS)
                exact = _date_equal_by_day(ld_val, ad_val)
                soft = exact
                vector = _vector_similarity(
                    ld_val.isoformat() if ld_val else None,
                    ad_val.isoformat() if ad_val else None,
                )
            else:
                ln = _norm_text(live_val)
                an = _norm_text(agent_val)
                exact = 1.0 if (ln and an and ln == an) else 0.0
                soft = _soft_ratio(ln, an)
                vector = _vector_similarity(ln, an)
            
            # Track field-specific scores
            if canon not in field_scores:
                field_scores[canon] = {"exact": [], "soft": [], "vector": []}
            field_scores[canon]["exact"].append(exact)
            field_scores[canon]["soft"].append(soft)
            field_scores[canon]["vector"].append(vector)
                
            per_field_victim.append({
                "field": canon,
                "live_value": live_val,
                "agent_value": agent_val,
                "exact": round(exact, 4),
                "soft": round(soft, 4),
                "vector": round(vector, 4),
            })
            exacts_victim.append(exact)
            softs_victim.append(soft)
            vectors_victim.append(vector)
        
        all_exact_scores.extend(exacts_victim)
        all_soft_scores.extend(softs_victim)
        all_vector_scores.extend(vectors_victim)
        
        detailed_per_victim.append({
            "victimCompany": agent_company,
            "scores": {
                "exact_accuracy": round(sum(exacts_victim)/len(exacts_victim), 4),
                "soft_similarity": round(sum(softs_victim)/len(softs_victim), 4),
                "vector_similarity": round(sum(vectors_victim)/len(vectors_victim), 4),
            },
            "match": {
                "type": match_type,
                "victim_vector": round(victim_vector_score, 4),
                "matched_victim": _norm_text(live_doc.get("victim")),
            },
            "per_field": per_field_victim
        })

    # Calculate aggregate scores
    aggregate_exact_score = round(sum(all_exact_scores)/len(all_exact_scores), 4) if all_exact_scores else 0.0
    aggregate_soft_score = round(sum(all_soft_scores)/len(all_soft_scores), 4) if all_soft_scores else 0.0
    aggregate_vector_score = round(sum(all_vector_scores)/len(all_vector_scores), 4) if all_vector_scores else 0.0

    # Calculate per-field aggregate scores
    field_aggregate_scores = {}
    for field, scores in field_scores.items():
        exact_scores = scores["exact"]
        soft_scores = scores["soft"]
        vector_scores = scores["vector"]
        field_aggregate_scores[field] = {
            "exact_accuracy": round(sum(exact_scores)/len(exact_scores), 4) if exact_scores else 0.0,
            "soft_similarity": round(sum(soft_scores)/len(soft_scores), 4) if soft_scores else 0.0,
            "vector_similarity": round(sum(vector_scores)/len(vector_scores), 4) if vector_scores else 0.0,
            "sample_count": len(exact_scores)
        }

    result["detailed_per_victim"] = detailed_per_victim
    result["per_victim_match_count"] = len(detailed_per_victim)
    result["unmatched_victims"] = unmatched_victims
    result["unmatched_count"] = len(unmatched_victims)
    result["aggregate_scores"] = {
        "exact_accuracy": aggregate_exact_score,
        "soft_similarity": aggregate_soft_score,
        "vector_similarity": aggregate_vector_score,
    }
    result["field_aggregate_scores"] = field_aggregate_scores

    return result


async def import_group_victims(
    group_name: str,
    collection,
    dedupe_fields: Tuple[str, ...] = ("group", "victim", "domain"),
) -> None:
    data = await _fetch_group_victims(group_name)

    if not data:
        return

    if isinstance(data, dict):
        docs = [data]
    else:
        docs = [doc for doc in data if isinstance(doc, dict)]

    if not docs:
        return

    uniques = set()
    new_docs: List[Dict[str, Any]] = []

    for doc in docs:
        key_values = tuple((field, doc.get(field)) for field in dedupe_fields if doc.get(field) is not None)
        if not key_values:
            key = hash(json.dumps(doc, sort_keys=True))
        else:
            key = tuple(key_values)

        if key in uniques:
            continue

        filter_query = {field: doc.get(field) for field in dedupe_fields if doc.get(field) is not None}
        if filter_query:
            existing = await collection.find_one(filter_query)
            if existing:
                continue

        new_docs.append(doc)
        uniques.add(key)

    if new_docs:
        await collection.insert_many(new_docs)
        print(f"Inserted {len(new_docs)} ransomware.live victims for group '{group_name}' into {collection.name}")


async def _fetch_group_victims(group_name: str) -> Any:
    base_url = "https://api.ransomware.live/v2/groupvictims"
    url = f"{base_url}/{group_name}"
    loop = asyncio.get_running_loop()

    def _request():
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        return response.json()

    return await loop.run_in_executor(None, _request)


async def _best_group_name(target: str, collection, field: str) -> str:
    try:
        names = await collection.distinct(field)
    except Exception:  # pylint: disable=broad-except
        names = []

    target_norm = _norm_text(target) or target
    best_name = target
    best_score = -1.0

    for name in names:
        if not name:
            continue
        score = _soft_ratio(target_norm, _norm_text(name))
        if score > best_score:
            best_score = score
            best_name = name

    return best_name
