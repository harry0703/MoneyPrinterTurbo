# Multi-Scene Generation Improvement Plan

## 1. Background and Objectives

### 1.1 Current Implementation Issues

The current multi-scene generation implementation relies on LLM for basic scene division, but lacks semantic-aware scene boundary detection. This leads to several problems:

- Scene boundaries may not align with natural topic shifts
- Similar content may be split across different scenes
- Different content types (narrative, explanation, argumentation) use the same processing logic
- No configurable options for advanced scene clustering

### 1.2 Optimization Goals

1. Implement semantic-driven scene division based on:
   - Parallel relationships between described objects
   - Temporal segments of story development
   - Perspective shifts when observing事物
   - Topic focus transitions in discussions

2. Add post-processing clustering algorithm to refine scene boundaries

3. Introduce content-type-aware parameter optimization

4. Provide configurable options to enable/disable clustering functionality

---

## 2. Technical Architecture

### 2.1 Overall Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Video Script                              │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│              LLM Processing (Single Call)                        │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 1. Content Type Classification                          │    │
│  │ 2. Multi-Scene Script Generation                         │    │
│  │ 3. Scene Semantic Feature Extraction                     │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│           Post-Processing: Semantic Clustering                    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 1. Text Embedding (BERT-based)                           │    │
│  │ 2. Similarity Calculation                                │    │
│  │ 3. Hierarchical Clustering / DBSCAN                       │    │
│  │ 4. Content-Type-Adaptive Parameter Adjustment           │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Refined Scene Boundaries                        │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Key Components

1. **Content Type Classifier**: Classifies script into types (narrative, explanatory, argumentative, interview, etc.)

2. **Semantic Feature Extractor**: Extracts entities, topics, temporal, spatial features from script segments

3. **Adaptive Clustering Engine**: Applies content-type-specific clustering parameters

4. **Configuration Manager**: Controls clustering enable/disable and parameter settings

---

## 3. Detailed Design

### 3.1 Content Type Classification

#### 3.1.1 Content Types

| Type | Description | Typical Characteristics |
|------|-------------|----------------------|
| `narrative` | Storytelling with plot development | First-person perspective, temporal markers, character actions |
| `explanatory` | Teaching or explaining concepts | Definitions, examples, cause-effect relationships |
| `argumentative` | Persuasion or debate | Claims, evidence, counterarguments |
| `interview` | Q&A format | Questions and answers alternating |
| `informative` | Factual reporting | Statistics, quotes, neutral tone |
| `mixed` | Combination of above | Multiple characteristics present |

#### 3.1.2 Classification Prompt

```python
CLASSIFICATION_PROMPT = """
Analyze the following video script and classify its content type.

Content Types:
- narrative: Storytelling with plot development
- explanatory: Teaching or explaining concepts
- argumentative: Persuasion or debate
- interview: Q&A format
- informative: Factual reporting
- mixed: Combination of multiple types

Script:
{script_content}

Output Format:
- content_type: [one of the above types]
- confidence: [0.0-1.0]
- characteristics: [brief description of key features]
"""
```

### 3.2 Semantic Feature Extraction

#### 3.2.1 Feature Types

| Feature | Description | Extraction Method |
|---------|-------------|------------------|
| `entities` | People, places, organizations | Named Entity Recognition |
| `topics` | Main themes discussed | Topic Modeling (LDA) |
| `temporal_markers` | Time expressions | Regex + NLP |
| `spatial_markers` | Location/space references | NLP patterns |
| `viewpoint_shifts` | Changes in perspective | Semantic analysis |
| `topic_transitions` | Topic change indicators | Discourse markers |

#### 3.2.2 Feature Extraction Prompt

```python
FEATURE_EXTRACTION_PROMPT = """
Extract semantic features from each paragraph/sentence for scene clustering.

For the following script content:
{script_segments}

Extract:
1. Named entities (people, places, organizations)
2. Topic keywords
3. Temporal markers (if any)
4. Spatial markers (if any)
5. Discourse markers indicating topic shifts

Output a JSON array of feature dictionaries for each segment.
"""
```

### 3.3 Clustering Algorithm

#### 3.3.1 Algorithm Selection

- **Primary**: Hierarchical Clustering with Ward linkage
- **Alternative**: DBSCAN for density-based clustering
- **Fallback**: K-means if computational resources are limited

#### 3.3.2 Algorithm-Specific Parameters

| Algorithm | Parameters | Description |
|-----------|------------|-------------|
| **Hierarchical** | `distance_threshold` | Distance threshold to form new clusters |
| **DBSCAN** | `eps`, `min_samples` | Epsilon (neighborhood radius), minimum samples in cluster |
| **K-means** | `n_clusters` | Number of clusters to form |

#### 3.3.3 Content-Type-Adaptive Parameters

| Content Type | Similarity Threshold | Min Cluster Size | Max Clusters | Algorithm |
|--------------|---------------------|-----------------|--------------|-----------|
| `narrative` | 0.75 | 2 | 8 | hierarchical |
| `explanatory` | 0.70 | 2 | 10 | hierarchical |
| `argumentative` | 0.65 | 2 | 6 | hierarchical |
| `interview` | 0.60 | 2 | 12 | hierarchical |
| `informative` | 0.70 | 2 | 10 | hierarchical |
| `mixed` | 0.75 | 3 | 8 | dbscan |

#### 3.3.4 Parameter Mapping

The system automatically maps user-friendly parameters to algorithm-specific parameters:

| User Parameter | Hierarchical | DBSCAN | K-means |
|----------------|--------------|--------|---------|
| `similarity_threshold` | `1 - distance_threshold` | `1 - eps` | N/A |
| `min_cluster_size` | N/A | `min_samples` | N/A |
| `max_clusters` | N/A | N/A | `n_clusters` |

#### 3.3.5 Clustering Implementation

```python
def semantic_clustering(segments: List[Dict], content_type: str, config: Dict) -> List[List[int]]:
    """
    Perform semantic clustering on script segments.

    Args:
        segments: List of script segment dictionaries with features
        content_type: Classified content type
        config: Clustering configuration

    Returns:
        List of cluster indices
    """
    # Get selected algorithm
    algorithm = config.get('clustering_algorithm', 'hierarchical')
    
    # Get content-type-adaptive parameters
    content_params = CLUSTERING_PARAMS.get(content_type, CLUSTERING_PARAMS['mixed'])
    
    # Generate text embeddings
    embeddings = generate_embeddings([seg['text'] for seg in segments])

    # Calculate similarity matrix
    similarity_matrix = cosine_similarity(embeddings)

    # Apply clustering algorithm with algorithm-specific parameters
    if algorithm == 'hierarchical':
        # Use hierarchical-specific parameters
        distance_threshold = config.get('hierarchical_distance_threshold', 1 - content_params['similarity_threshold'])
        min_cluster_size = config.get('hierarchical_min_cluster_size', content_params['min_cluster_size'])
        
        clusters = hierarchical_clustering(
            similarity_matrix,
            distance_threshold=distance_threshold,
            min_cluster_size=min_cluster_size
        )
        
        # Respect max_clusters limit
        if len(set(clusters)) > content_params['max_clusters']:
            clusters = merge_small_clusters(clusters, content_params['max_clusters'])
            
    elif algorithm == 'dbscan':
        # Use DBSCAN-specific parameters
        eps = config.get('dbscan_eps', 1 - content_params['similarity_threshold'])
        min_samples = config.get('dbscan_min_samples', content_params['min_cluster_size'])
        
        clusters = dbscan_clustering(
            similarity_matrix,
            eps=eps,
            min_samples=min_samples
        )
        
        # Respect max_clusters limit
        if len(set(clusters)) > content_params['max_clusters']:
            clusters = merge_small_clusters(clusters, content_params['max_clusters'])
            
    else:  # kmeans
        # Use K-means-specific parameters
        n_clusters = config.get('kmeans_n_clusters', content_params['max_clusters'])
        max_iter = config.get('kmeans_max_iter', 300)
        
        # Ensure n_clusters doesn't exceed number of segments
        n_clusters = min(n_clusters, len(segments))
        
        clusters = kmeans_clustering(
            similarity_matrix,
            n_clusters=n_clusters,
            max_iter=max_iter
        )

    return clusters
```

### 3.4 Merged LLM Call Strategy

#### 3.4.1 Single-Prompt Design

```python
MERGED_ANALYSIS_PROMPT = """
# Role: Multi-Scene Script Analyzer

## Task
Analyze the video script and generate a structured multi-scene breakdown with semantic clustering optimization.

## Input Script
{script_content}

## Requirements

### 1. Content Type Classification
Classify the script into one of these types:
- narrative: Storytelling with plot development
- explanatory: Teaching or explaining concepts
- argumentative: Persuasion or debate
- interview: Q&A format
- informative: Factual reporting
- mixed: Combination of multiple types

### 2. Scene Division
Divide the script into semantic scenes based on:
- Parallel relationships between described objects
- Temporal segments of story development
- Perspective shifts when observing事物
- Topic focus transitions

### 3. Scene Structure
For each scene, provide:
- scene_id: Unique identifier
- title: Scene title
- camera: Visual/camera description
- script: Narration/script content
- start_time: Estimated start time
- end_time: Estimated end time
- semantic_features:
  - entities: List of named entities
  - topics: List of main topics
  - temporal_markers: Time expressions
  - spatial_markers: Location references
  - discourse_markers: Transition indicators

### 4. Content Type Adaptation Notes
Provide recommendations for clustering parameters based on content type:
- suggested_similarity_threshold: 0.0-1.0
- suggested_min_cluster_size: integer
- suggested_max_clusters: integer

## Output Format
Return a JSON object with:
{
  "content_type": "...",
  "content_type_confidence": 0.0-1.0,
  "scenes": [...],
  "clustering_recommendations": {...}
}
"""
```

---

## 4. Configuration Management

### 4.1 Configuration Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `clustering_algorithm` | string | "hierarchical" | Clustering algorithm: hierarchical, dbscan, kmeans |
| `content_type_adaptive` | bool | true | Enable content-type-adaptive parameter adjustment |
| `embedding_model` | string | "sentence-transformers/all-MiniLM-L6-v2" | Text embedding model |

#### 4.1.1 Algorithm-Specific Parameters

**Hierarchical Clustering**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `hierarchical_distance_threshold` | float | 0.3 | Distance threshold for forming new clusters (higher = more clusters) |
| `hierarchical_min_cluster_size` | int | 2 | Minimum number of segments per cluster |

**DBSCAN**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dbscan_eps` | float | 0.3 | Epsilon (neighborhood radius) |
| `dbscan_min_samples` | int | 2 | Minimum samples required to form a cluster |

**K-means**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `kmeans_n_clusters` | int | 8 | Number of clusters to form |
| `kmeans_max_iter` | int | 300 | Maximum number of iterations |

### 4.2 Configuration File Integration

```toml
[multi_scene]
# Clustering algorithm selection
clustering_algorithm = "hierarchical"  # hierarchical, dbscan, kmeans

# Content-type-adaptive parameter adjustment
content_type_adaptive = true

# Text embedding model (for similarity calculation)
embedding_model = "sentence-transformers/all-MiniLM-L6-v2"

# Hierarchical clustering parameters
hierarchical_distance_threshold = 0.3
hierarchical_min_cluster_size = 2

# DBSCAN parameters
dbscan_eps = 0.3
dbscan_min_samples = 2

# K-means parameters
kmeans_n_clusters = 8
kmeans_max_iter = 300
```

### 4.3 UI Integration

- Display content type classification result after parsing
- Show clustering parameters used in logs
- No toggle switch - clustering is automatically enabled

---

## 5. Implementation Plan

### 5.1 Phase 1: Core Components

1. **Content Type Classifier**
   - Implement content type classification function
   - Integrate into `scene_parser.py`

2. **Semantic Feature Extractor**
   - Implement feature extraction based on LLM
   - Add feature fields to scene structure

### 5.2 Phase 2: Clustering Algorithm

1. **Text Embedding Module**
   - Integrate sentence-transformers library
   - Implement embedding generation function
   - Add caching mechanism for performance

2. **Clustering Engine**
   - Implement hierarchical clustering
   - Implement DBSCAN alternative
   - Add content-type-adaptive parameter selection

3. **Scene Boundary Refinement**
   - Merge/split scenes based on clustering results
   - Update scene timing and metadata

### 5.3 Phase 3: Configuration and UI

1. **Configuration Manager**
   - Add all new parameters to config.toml
   - Implement parameter validation

2. **UI Enhancements**
   - Add clustering toggle in scene management panel
   - Display content type and clustering info
   - Add logging for clustering decisions

### 5.4 Phase 4: Testing and Optimization

1. **Unit Tests**
   - Test content type classification accuracy
   - Test clustering algorithm correctness

2. **Integration Tests**
   - End-to-end scene generation with clustering

3. **Performance Optimization**
   - Optimize embedding generation
   - Add result caching

4. **Parameter Tuning**
   - Test different content types
   - Tune similarity thresholds

---

## 6. Expected Outcomes

### 6.1 Quality Improvements

| Metric | Current | Expected | Improvement |
|--------|---------|----------|-------------|
| Scene semantic coherence | ~70% | ~90% | +20% |
| Boundary accuracy | ~75% | ~88% | +13% |
| Topic continuity | ~65% | ~85% | +20% |
| Overall user satisfaction | - | +15% | - |

### 6.2 Performance Metrics

| Metric | Target | Notes |
|--------|--------|-------|
| Additional latency | <2s | For typical script (500-2000 chars) |
| Memory overhead | <500MB | For embedding cache |
| Clustering success rate | >95% | Fallback to LLM-only if fails |

### 6.3 User Experience

- Seamless integration with existing workflow
- Optional advanced features for power users
- Clear feedback on clustering decisions
- Configurable to match different use cases

---

## 7. Risk Mitigation

### 7.1 Technical Risks

| Risk | Mitigation |
|------|------------|
| Embedding model unavailable | Fallback to LLM-based similarity |
| Clustering quality poor | Fallback to LLM-only scene division |
| Performance degradation | Add caching, async processing |

### 7.2 User Adoption Risks

| Risk | Mitigation |
|------|------------|
| Performance concerns | Optimize embedding generation, add caching |
| Unclear benefits | Add explanatory UI text |
| Configuration confusion | Sensible defaults, tooltips |

---

## 8. Future Enhancements

1. **Visual Scene Preview**: Generate thumbnail previews for each scene
2. **Scene Similarity Suggestions**: Recommend merging similar scenes
3. **Cross-Video Clustering**: Apply clustering across multiple related videos
4. **Adaptive Learning**: Learn from user corrections to improve clustering
5. **Multi-Modal Features**: Incorporate audio/speech patterns into clustering

---

## 9. Appendix

### 9.1 Glossary

- **Semantic Clustering**: Grouping text segments based on meaning similarity
- **Content Type**: Classification of script style (narrative, explanatory, etc.)
- **Scene Boundary**: Points where scenes transition
- **Text Embedding**: Vector representation of text for similarity calculation

### 9.2 References

- Sentence Transformers: https://www.sbert.net/
- Scikit-learn Clustering: https://scikit-learn.org/stable/modules/clustering.html
- Hierarchical Clustering: Ward's method

### 9.3 Dependencies

```
sentence-transformers>=2.2.0
scikit-learn>=1.0.0
numpy>=1.21.0
```

---

## 10. Review Checklist

- [ ] Content type classification accuracy validated
- [ ] Clustering parameters optimized for each content type
- [ ] Algorithm-specific parameters properly configured
- [ ] Configuration parameters documented
- [ ] UI integration complete
- [ ] Performance benchmarks met
- [ ] Fallback mechanisms tested
- [ ] Documentation updated
- [ ] Unit tests passing
- [ ] Integration tests passing
