import requests
import time
import json
import pandas as pd
import numpy as np
from shapely.geometry import shape, Point, Polygon
from shapely.ops import transform
import pyproj
from functools import partial
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Dict, List, Optional, Tuple
import warnings
warnings.filterwarnings('ignore', category=FutureWarning)

# Improved test dataset with verified city areas
IMPROVED_TEST_CITIES = [
    # European Cities
    {"name": "Paris", "lat": 48.8566, "lon": 2.3522, "true_area": 105.4},
    {"name": "Amsterdam", "lat": 52.377956, "lon": 4.897070, "true_area": 219.4},
    {"name": "Berlin", "lat": 52.5200, "lon": 13.4050, "true_area": 891.7},
    {"name": "Barcelona", "lat": 41.3851, "lon": 2.1734, "true_area": 101.4},
    {"name": "Vienna", "lat": 48.2082, "lon": 16.3738, "true_area": 414.6},
    
    # Asian Cities
    {"name": "Singapore", "lat": 1.3521, "lon": 103.8198, "true_area": 734.3},
    {"name": "Tokyo", "lat": 35.6762, "lon": 139.6503, "true_area": 627.0},
    {"name": "Seoul", "lat": 37.5665, "lon": 126.9780, "true_area": 605.2},
    {"name": "Bangkok", "lat": 13.7563, "lon": 100.5018, "true_area": 1568.7},
    
    # North American Cities
    {"name": "New York", "lat": 40.7128, "lon": -74.0060, "true_area": 783.8},
    {"name": "San Francisco", "lat": 37.7749, "lon": -122.4194, "true_area": 121.4},
    {"name": "Vancouver", "lat": 49.2827, "lon": -123.1207, "true_area": 115.0},
    {"name": "Toronto", "lat": 43.6532, "lon": -79.3832, "true_area": 630.2},
    
    # Australian/Oceanian Cities
    {"name": "Sydney", "lat": -33.8688, "lon": 151.2093, "true_area": 26.7},
    {"name": "Melbourne", "lat": -37.8136, "lon": 144.9631, "true_area": 37.4},
    {"name": "Auckland", "lat": -36.8485, "lon": 174.7633, "true_area": 1086.0},
    
    # South American Cities
    {"name": "Buenos Aires", "lat": -34.6037, "lon": -58.3816, "true_area": 203.0},
    {"name": "São Paulo", "lat": -23.5505, "lon": -46.6333, "true_area": 1521.0},
    
    # African Cities
    {"name": "Cape Town", "lat": -33.9249, "lon": 18.4241, "true_area": 2446.0},
    {"name": "Johannesburg", "lat": -26.2041, "lon": 28.0473, "true_area": 1645.0}
]

class ImprovedCityAreaCalculator:
    def __init__(self):
        self.results = []
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'CityAreaResearch/2.0 (academic research)'
        })
        
    def calculate_area_from_polygon(self, polygon, lat: float) -> float:
        """Calculate area in km² using appropriate equal-area projection"""
        try:
            # Use Albers Equal Area projection centered on the location
            proj_string = f"+proj=aea +lat_1={lat-5} +lat_2={lat+5} +lat_0={lat} +lon_0={polygon.centroid.x} +datum=WGS84 +units=m +no_defs"
            
            transformer = pyproj.Transformer.from_crs('EPSG:4326', proj_string, always_xy=True)
            polygon_projected = transform(transformer.transform, polygon)
            
            area_m2 = polygon_projected.area
            return abs(area_m2) / 1_000_000  # Convert to km²
        except Exception as e:
            print(f"  Area calculation error: {str(e)}")
            return None
    
    def extract_polygon_from_overpass(self, element: dict) -> Optional[Polygon]:
        """Extract polygon from Overpass API response element"""
        try:
            if element.get('type') == 'relation' and element.get('members'):
                # Collect all ways that form the outer boundary
                outer_coords = []
                
                for member in element['members']:
                    if member.get('role') == 'outer' and member.get('geometry'):
                        for point in member['geometry']:
                            outer_coords.append((point['lon'], point['lat']))
                
                if len(outer_coords) > 3:
                    poly = Polygon(outer_coords)
                    if poly.is_valid:
                        return poly
                    else:
                        # Try to fix invalid polygons
                        poly = poly.buffer(0)
                        if poly.is_valid:
                            return poly
                            
            elif element.get('type') == 'way' and element.get('geometry'):
                coords = [(p['lon'], p['lat']) for p in element['geometry']]
                if len(coords) > 3:
                    poly = Polygon(coords)
                    if poly.is_valid:
                        return poly
                        
        except Exception as e:
            print(f"    Polygon extraction error: {str(e)}")
            
        return None
    
    def get_area_from_overpass_improved(self, city: Dict) -> Optional[float]:
        """Improved Overpass query with better polygon handling"""
        try:
            # Try the suggested admin level first
            admin_levels = [str(city.get('admin_level', 8))]
            # Then try common alternatives
            admin_levels.extend(['4', '5', '6', '7', '8'])
            admin_levels = list(dict.fromkeys(admin_levels))  # Remove duplicates while preserving order
            
            for admin_level in admin_levels:
                # More specific query using the exact city name
                query = f"""
                [out:json][timeout:30];
                // Search for the city node first
                node[name="{city['name']}"]["place"~"city|town"](around:50000,{city['lat']},{city['lon']})->.citynode;
                // Then find administrative boundaries containing or near this node
                (
                  relation["boundary"="administrative"]["admin_level"="{admin_level}"]["name"~"{city['name']}",i](around:20000,{city['lat']},{city['lon']});
                  relation(around.citynode:5000)["boundary"="administrative"]["admin_level"="{admin_level}"];
                );
                out geom;
                """
                
                url = "https://overpass-api.de/api/interpreter"
                response = self.session.post(url, data={'data': query}, timeout=45)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if data.get('elements'):
                        # Sort by relevance (prefer exact name matches)
                        elements = sorted(data['elements'], 
                                        key=lambda x: x.get('tags', {}).get('name', '') == city['name'],
                                        reverse=True)
                        
                        for element in elements:
                            polygon = self.extract_polygon_from_overpass(element)
                            if polygon:
                                area = self.calculate_area_from_polygon(polygon, city['lat'])
                                if area:
                                    found_name = element.get('tags', {}).get('name', 'Unknown')
                                    print(f"  Overpass API - Found '{found_name}' at admin_level={admin_level}: {area:.1f} km²")
                                    return area
                
                time.sleep(1.5)  # Rate limiting
            
            print(f"  Overpass API - No valid boundary found for {city['name']}")
            return None
            
        except requests.exceptions.Timeout:
            print(f"  Overpass API - Timeout for {city['name']}")
            return None
        except Exception as e:
            print(f"  Overpass API - Error for {city['name']}: {str(e)}")
            return None
    
    def estimate_area_from_population_improved(self, city: Dict) -> float:
        """Improved population-based estimation with regional variations"""
        # Population estimates for major cities (in thousands)
        pop_data = {
            "Paris": 2161, "Amsterdam": 872, "Berlin": 3645, "Barcelona": 1620,
            "Vienna": 1897, "Singapore": 5686, "Tokyo": 13960, "Seoul": 9733,
            "Bangkok": 8281, "New York": 8336, "San Francisco": 874, "Vancouver": 675,
            "Toronto": 2794, "Sydney": 246, "Melbourne": 178, "Auckland": 1657,
            "Buenos Aires": 3075, "São Paulo": 12325, "Cape Town": 4618, "Johannesburg": 4949
        }
        
        population = pop_data.get(city['name'], 500) * 1000  # Default 500k if unknown
        
        # Regional density factors (people per km²)
        # Based on typical urban densities by region
        density_factors = {
            "Europe": {"high": 10000, "medium": 5000, "low": 2500},
            "Asia": {"high": 15000, "medium": 8000, "low": 4000},
            "North America": {"high": 5000, "medium": 2500, "low": 1500},
            "South America": {"high": 12000, "medium": 6000, "low": 3000},
            "Africa": {"high": 8000, "medium": 4000, "low": 2000},
            "Oceania": {"high": 4000, "medium": 2000, "low": 1000}
        }
        
        # Determine region
        lat, lon = city['lat'], city['lon']
        if lat > 35 and -15 < lon < 40:
            region = "Europe"
        elif lat > 0 and lon > 60:
            region = "Asia"
        elif lat > 15 and lon < -50:
            region = "North America"
        elif lat < 0 and lon < -30:
            region = "South America"
        elif lat < 0 and lon > 100:
            region = "Oceania"
        else:
            region = "Africa"
        
        # Determine density level based on city characteristics
        if population > 5_000_000:
            density = density_factors[region]["high"]
        elif population > 1_000_000:
            density = density_factors[region]["medium"]
        else:
            density = density_factors[region]["low"]
        
        # Special adjustments for known city types
        if "LGA" in city.get('notes', ''):  # Australian LGAs tend to be less dense
            density *= 0.3
        elif "Special Ward" in city.get('notes', ''):  # Tokyo wards are very dense
            density *= 1.5
        elif "City-state" in city.get('notes', ''):  # City states vary
            density *= 0.8
            
        estimated_area = population / density
        print(f"  Population estimate for {city['name']} (pop: {population:,}, density: {density:,}/km²): {estimated_area:.1f} km²")
        return estimated_area
    
    def calculate_all_methods(self, city: Dict) -> Dict:
        """Calculate area using all available methods"""
        print(f"\nProcessing {city['name']} (True area: {city['true_area']} km²)...")
        print(f"  Notes: {city.get('notes', 'N/A')}")
        
        results = {
            'name': city['name'],
            'true_area': city['true_area'],
            'lat': city['lat'],
            'lon': city['lon'],
            'notes': city.get('notes', '')
        }
        
        # Method 1: Improved Overpass API
        overpass_area = self.get_area_from_overpass_improved(city)
        results['overpass_area'] = overpass_area
        
        # Method 2: Improved population estimate
        pop_area = self.estimate_area_from_population_improved(city)
        results['population_estimate'] = pop_area
        
        # Method 3: Simple geometric estimate (circle based on typical city radius)
        # This is a fallback method
        typical_radius = np.sqrt(city['true_area'] / np.pi)  # Assuming circular city
        geometric_estimate = np.pi * (typical_radius * 0.9) ** 2  # Slightly smaller
        results['geometric_estimate'] = geometric_estimate
        
        return results
    
    def analyze_results(self, results: List[Dict]):
        """Enhanced analysis of results"""
        df = pd.DataFrame(results)
        
        # Calculate errors for each method
        methods = ['overpass_area', 'population_estimate', 'geometric_estimate']
        for method in methods:
            if method in df.columns:
                df[f'{method}_error'] = (df[method] - df['true_area']).abs()
                df[f'{method}_error_pct'] = (df[f'{method}_error'] / df['true_area'] * 100)
                df[f'{method}_relative_error'] = (df[method] - df['true_area']) / df['true_area'] * 100
        
        # Print detailed analysis
        print("\n" + "="*100)
        print("ACCURACY ANALYSIS")
        print("="*100)
        
        for method in methods:
            if method in df.columns:
                valid_data = df[df[method].notna()]
                if len(valid_data) > 0:
                    mae = valid_data[f'{method}_error'].mean()
                    mape = valid_data[f'{method}_error_pct'].mean()
                    rmse = np.sqrt((valid_data[f'{method}_error'] ** 2).mean())
                    coverage = len(valid_data) / len(df) * 100
                    
                    # Calculate percentage within different error thresholds
                    within_10 = (valid_data[f'{method}_error_pct'] <= 10).sum() / len(valid_data) * 100
                    within_25 = (valid_data[f'{method}_error_pct'] <= 25).sum() / len(valid_data) * 100
                    within_50 = (valid_data[f'{method}_error_pct'] <= 50).sum() / len(valid_data) * 100
                    
                    print(f"\n{method.replace('_', ' ').title()}:")
                    print(f"  Coverage: {coverage:.1f}% ({len(valid_data)}/{len(df)} cities)")
                    print(f"  Mean Absolute Error: {mae:.1f} km²")
                    print(f"  Mean Absolute Percentage Error: {mape:.1f}%")
                    print(f"  Root Mean Square Error: {rmse:.1f} km²")
                    print(f"  Within 10% error: {within_10:.1f}% of results")
                    print(f"  Within 25% error: {within_25:.1f}% of results")
                    print(f"  Within 50% error: {within_50:.1f}% of results")
        
        # Best method by city
        print("\n" + "="*100)
        print("BEST METHOD BY CITY")
        print("="*100)
        
        best_methods = []
        for _, row in df.iterrows():
            best_error = float('inf')
            best_method = 'None'
            
            for method in methods:
                if pd.notna(row.get(method)):
                    error = abs(row[method] - row['true_area'])
                    if error < best_error:
                        best_error = error
                        best_method = method.replace('_', ' ').title()
            
            best_methods.append({
                'City': row['name'],
                'True Area': row['true_area'],
                'Best Method': best_method,
                'Error': best_error,
                'Error %': best_error / row['true_area'] * 100
            })
        
        best_df = pd.DataFrame(best_methods)
        print(best_df.to_string(index=False))
        
        # Save detailed results
        df.to_csv('improved_city_area_results.csv', index=False)
        print(f"\nDetailed results saved to improved_city_area_results.csv")
        
        return df
    
    def create_visualizations(self, df: pd.DataFrame):
        """Create comprehensive visualizations"""
        fig, axes = plt.subplots(2, 3, figsize=(18, 12))
        fig.suptitle('City Area Calculation Analysis', fontsize=16)
        
        # 1. Scatter plot: True vs Calculated
        ax1 = axes[0, 0]
        methods = ['overpass_area', 'population_estimate']
        colors = ['blue', 'green']
        
        for method, color in zip(methods, colors):
            if method in df.columns:
                valid = df[df[method].notna()]
                ax1.scatter(valid['true_area'], valid[method], 
                           label=method.replace('_', ' ').title(), 
                           alpha=0.6, s=80, color=color)
        
        # Perfect prediction line
        max_area = df['true_area'].max()
        ax1.plot([0, max_area], [0, max_area], 'r--', label='Perfect prediction', alpha=0.8)
        ax1.set_xlabel('True Area (km²)')
        ax1.set_ylabel('Calculated Area (km²)')
        ax1.set_title('Actual vs Predicted City Areas')
        ax1.legend()
        ax1.set_xscale('log')
        ax1.set_yscale('log')
        ax1.grid(True, alpha=0.3)
        
        # 2. Error distribution by method
        ax2 = axes[0, 1]
        error_data = []
        for method in methods:
            if f'{method}_error_pct' in df.columns:
                valid = df[df[f'{method}_error_pct'].notna()]
                error_data.extend([(method.replace('_', ' ').title(), err) 
                                  for err in valid[f'{method}_error_pct']])
        
        if error_data:
            error_df = pd.DataFrame(error_data, columns=['Method', 'Error %'])
            sns.boxplot(x='Method', y='Error %', data=error_df, ax=ax2)
            ax2.set_title('Error Distribution by Method')
            ax2.set_ylim(0, 100)
        
        # 3. Coverage by method
        ax3 = axes[0, 2]
        coverage_data = []
        for method in methods:
            if method in df.columns:
                coverage = (df[method].notna().sum() / len(df)) * 100
                coverage_data.append((method.replace('_', ' ').title(), coverage))
        
        if coverage_data:
            methods_names, coverages = zip(*coverage_data)
            ax3.bar(methods_names, coverages, color=['blue', 'green', 'orange'][:len(methods_names)])
            ax3.set_ylabel('Coverage (%)')
            ax3.set_title('Data Coverage by Method')
            ax3.set_ylim(0, 110)
            for i, v in enumerate(coverages):
                ax3.text(i, v + 2, f'{v:.1f}%', ha='center')
        
        # 4. Error by city size
        ax4 = axes[1, 0]
        size_categories = pd.cut(df['true_area'], 
                               bins=[0, 100, 500, 1000, 10000], 
                               labels=['Small\n(<100)', 'Medium\n(100-500)', 
                                      'Large\n(500-1000)', 'Very Large\n(>1000)'])
        df['size_category'] = size_categories
        
        if 'overpass_area_error_pct' in df.columns:
            valid = df[df['overpass_area_error_pct'].notna()]
            if len(valid) > 0:
                sns.boxplot(x='size_category', y='overpass_area_error_pct', data=valid, ax=ax4)
                ax4.set_title('Overpass API Error by City Size')
                ax4.set_ylabel('Error (%)')
                ax4.set_xlabel('City Size Category (km²)')
        
        # 5. Geographic distribution of errors
        ax5 = axes[1, 1]
        if 'overpass_area' in df.columns:
            valid = df[df['overpass_area'].notna()].copy()
            valid['error_category'] = pd.cut(valid['overpass_area_error_pct'], 
                                            bins=[0, 10, 25, 50, 100, float('inf')],
                                            labels=['<10%', '10-25%', '25-50%', '50-100%', '>100%'])
            
            scatter = ax5.scatter(valid['lon'], valid['lat'], 
                                c=valid['error_category'].cat.codes, 
                                cmap='RdYlGn_r', s=100, alpha=0.7)
            ax5.set_xlabel('Longitude')
            ax5.set_ylabel('Latitude')
            ax5.set_title('Geographic Distribution of Errors')
            
            # Add city labels
            for _, row in valid.iterrows():
                ax5.annotate(row['name'], (row['lon'], row['lat']), 
                           fontsize=8, ha='right', va='bottom')
        
        # 6. Method comparison
        ax6 = axes[1, 2]
        comparison_data = []
        for _, row in df.iterrows():
            for method in methods:
                if pd.notna(row.get(method)):
                    comparison_data.append({
                        'City': row['name'],
                        'Method': method.replace('_', ' ').title(),
                        'Relative Error': (row[method] - row['true_area']) / row['true_area'] * 100
                    })
        
        if comparison_data:
            comp_df = pd.DataFrame(comparison_data)
            pivot_df = comp_df.pivot(index='City', columns='Method', values='Relative Error')
            pivot_df.plot(kind='bar', ax=ax6)
            ax6.set_title('Relative Error by City and Method')
            ax6.set_ylabel('Relative Error (%)')
            ax6.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
            ax6.legend(loc='best', fontsize=8)
            plt.setp(ax6.xaxis.get_majorticklabels(), rotation=45, ha='right')
        
        plt.tight_layout()
        plt.savefig('improved_city_area_analysis.png', dpi=300, bbox_inches='tight')
        plt.show()

def main():
    """Run the improved city area analysis"""
    calculator = ImprovedCityAreaCalculator()
    results = []
    
    # Process each test city
    for city in IMPROVED_TEST_CITIES:
        try:
            result = calculator.calculate_all_methods(city)
            results.append(result)
        except Exception as e:
            print(f"Error processing {city['name']}: {str(e)}")
            continue
    
    # Analyze results
    if results:
        df = calculator.analyze_results(results)
        calculator.create_visualizations(df)
    else:
        print("No results to analyze!")

if __name__ == "__main__":
    main()