# UNESCO-Map

A map-based visualizer that displays UNESCO World Heritage Sites around the world using markers and clustering for easy exploration. Users can zoom, pan, and discover site details directly on the map. 

![UNESCO Map Demo](demo.png)

*Explore heritage sites globally.*

---

### Features
- **Interactive Map:** Pan and zoom to discover sites across all continents.
- **Marker Clustering:** Uses `Leaflet.markercluster` to manage high-density areas (like Europe) for better performance and readability.
- **Site Details:** Click on markers to view metadata about specific World Heritage Sites.
- **Timeline:** Drag timeline to filter by the founding of UNESCO site in human history. 
### Future Improvements
- **Refine Date Extraction:** Improve the Natural Language Processing (NLP) or Regex patterns used for extracting inscription dates from site descriptions. 

### Dependencies
- [Leaflet](https://leafletjs.com/)
- [Leaflet.markercluster](https://github.com/Leaflet/Leaflet.markercluster) (`v1.5.3`)

### To Run
1. Start a local development server at base directory:
   ```bash
   python3 -m http.server 8000
   ```
2. Link: http://localhost:8000/index/