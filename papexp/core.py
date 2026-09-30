#!/usr/bin/env python3

import json
import os
import shutil
from base64 import b64encode
from http.client import HTTPSConnection

import pathlib

import yaml

import requests
from dotenv import load_dotenv
load_dotenv()

email = os.environ['PAPRIKA_EMAIL']
password = os.environ['PAPRIKA_PASSWORD']

c = HTTPSConnection("www.paprikaapp.com")

userAndPass = b64encode(bytes(email+":"+password, 'utf-8')).decode("ascii")
headers = { 'Authorization' : 'Basic %s' %  userAndPass }

def get(path):
    c.request('GET', path, headers=headers)
    res = c.getresponse()
    return res.read()

def get_result(path, retries=2):
    """Fetch a sync endpoint and return payload['result'].

    The v1 sync endpoints intermittently answer with an error payload that has
    no 'result' key (observed on /sync/photos/); retry once before giving up.
    """
    for attempt in range(retries):
        data = get(path)
        try:
            return json.loads(data)['result']
        except (KeyError, ValueError):
            if attempt < retries - 1:
                print('  no result in payload for', path, '- retrying')
    return None

def check_and_run():
    pathlib.Path('_data').mkdir(parents=True, exist_ok=True)
    try:
        with open(r'./_data/recipes_status.json', 'rb') as file:
            old_data = file.read()
    except IOError as error:
        open(r'./_data/recipes_status.json', 'wb+').close()
        old_data = "{}"
    new_data = get('/api/v1/sync/status/')
    if new_data != old_data:
        with open(r'./_data/recipes_status.json', 'wb+') as file:
            file.write(new_data)
        export_recipes()

def export_recipes():

    pathlib.Path(r'_data').mkdir(parents=True, exist_ok=True)
    pathlib.Path('assets/images/recipes').mkdir(parents=True, exist_ok=True)

    categories = {}
    category_items = get_result('/api/v1/sync/categories/')
    if category_items is None:
        print('no category list in payload; continuing without categories')
        category_items = []
    for item in category_items:
        categories[item['uid']] = item['name']

    recipes = []
    downloaded = 0
    stats = {'photo': 0, 'photo_large': 0, 'photo_url': 0, 'photo_url_uploads': 0}
    sample_fields = None

    recipe_items = get_result('/api/v1/sync/recipes/')
    if recipe_items is None:
        print('no recipe list in payload; aborting export (keeping last recipes.yaml)')
        return

    for item in recipe_items:
        recipe = get_result('/api/v1/sync/recipe/'+item['uid']+'/')
        if recipe is None:
            print('  no data for recipe', item['uid'], '- skipping')
            continue
        # https://gist.github.com/mattdsteele/7386ec363badfdeaad05a418b9a1f30a
        print(recipe['name'])

        for k in ('photo', 'photo_large'):
            if recipe.get(k):
                stats[k] += 1
        pu = recipe.get('photo_url') or ''
        if pu:
            stats['photo_url'] += 1
        if 'uploads.paprikaapp.com' in pu:
            stats['photo_url_uploads'] += 1
        if sample_fields is None and any((recipe.get('photo'), recipe.get('photo_large'), recipe.get('photo_url'))):
            sample_fields = {k: str(recipe.get(k))[:70] for k in ('photo', 'photo_large', 'photo_url')}

        # photo_url (the server-hosted image) is now served directly on the
        # recipe payload; older payloads required a /sync/photo/<addr>/ lookup
        # keyed by photo_large. The image host has drifted over time:
        #   http://uploads.paprikaapp.com.s3.amazonaws.com/...  (historic)
        #   https://uploads.paprikaapp.com/...                  (current)
        if recipe.get('photo_large'):
            recipe['photo'] = recipe['photo_large']
            addr = os.path.splitext(recipe['photo_large'])[0]
            photo_data = get_result('/api/v1/sync/photo/'+addr+'/')
            if photo_data and photo_data.get('photo_url'):
                recipe['photo_url'] = photo_data['photo_url']
            elif not pu:
                print('  no photo data for', recipe['name'], '- skipping')

        photo_addr = (recipe.get('photo') or '').split('/')[-1]
        pu = recipe.get('photo_url') or ''
        if photo_addr:
            if pu and 'uploads.paprikaapp.com' in pu:
                if '.' not in photo_addr:
                    photo_addr += '.jpg'
                try:
                    resp = requests.get(pu, stream=True)
                    resp.raise_for_status()
                    with open('assets/images/recipes/'+photo_addr, 'wb') as local_file:
                        resp.raw.decode_content = True
                        shutil.copyfileobj(resp.raw, local_file)
                    recipe['image_url'] = 'images/recipes/'+photo_addr
                    downloaded += 1
                except Exception as exc:
                    print('  image download failed for', recipe['name'], '-', exc)
            elif pu:
                print('  image url on unexpected host for', recipe['name'], '-', pu[:60])

        for photo_key in ('photo_url', 'photo', 'hash', 'photo_hash', 'photo_large'):
            recipe.pop(photo_key, None)

        recipe['photos'] = []

        if recipe['directions']:
            directions = recipe['directions'].split('\n')
            recipe['directions'] = []
            for direction in directions:
                if direction != '':
                    recipe['directions'].append(direction)

        if recipe['ingredients']:
            ingredients = recipe['ingredients'].split('\n')
            recipe['ingredients'] = []
            for ingredient in ingredients:
                if ingredient != '':
                    recipe['ingredients'].append(ingredient)

        if recipe['categories']:
            categoryList = []
            for category in recipe['categories']:
                categoryList.append(categories.get(category, category))
            recipe['categories'] = categoryList

        # picture_tag can only process local files; external source URLs
        # (e.g. imported-recipe image_urls) hard-fail the jekyll build
        if recipe.get('image_url') and str(recipe['image_url']).startswith(('http://', 'https://')):
            recipe['image_url'] = None

        recipes.append(recipe)

    # this gets all photos
    print("\n\n")
    print("Photos")
    photo_downloads = 0
    photos = get_result('/api/v1/sync/photos/')
    if photos is None:
        print('no photo list in payload; skipping photo export')
        photos = []
    for item in photos:
        photo = get_result('/api/v1/sync/photo/'+item['uid']+'/')
        if photo is None:
            print('  no data for photo item', item.get('uid'), '- skipping')
            continue
        rec = [x for x in recipes if x['uid'] == photo.get('recipe_uid')]
        if not rec:
            print('skipping photo with no matching recipe:', photo.get('name', photo.get('uid', '?')))
            continue
        if not photo.get('photo_url'):
            print('skipping photo without photo_url:', photo.get('name', photo.get('uid', '?')))
            continue
        filename = (photo.get('filename') or '').split('/')[-1]
        if not filename:
            print('skipping photo without filename:', photo.get('name', photo.get('uid', '?')))
            continue
        print(rec[0]['name'])
        # create newphoto dict with uid and filename
        newphoto = {}
        photo_name = photo['name']
        newphoto[photo_name] = 'images/recipes/'+filename
        rec[0]['photos'].append(newphoto)
        if not rec[0].get('image_url'):
            rec[0]['image_url'] = 'images/recipes/'+filename
        try:
            resp = requests.get(photo['photo_url'], stream=True)
            resp.raise_for_status()
            with open('assets/images/recipes/'+filename, 'wb') as local_file:
                resp.raw.decode_content = True
                shutil.copyfileobj(resp.raw, local_file)
            photo_downloads += 1
        except Exception as exc:
            print('  photo download failed for', photo.get('name', '?'), '-', exc)

    print('field stats:', stats)
    print('sample image fields:', sample_fields)
    print('recipe images downloaded:', downloaded)
    print('photo-collection images downloaded:', photo_downloads)
    print('recipes with images:', sum(1 for r in recipes if r.get('image_url')))

    with open(r'./_data/recipes.yaml', 'w') as file:
        yaml.safe_dump(recipes, file)

if __name__ == "__main__":
    check_and_run()
