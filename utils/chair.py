import sys
from nltk.stem import *
from nltk.corpus import wordnet as wn
import nltk
import json
from pattern.en import singularize
from pattern.en import tag 
import pdb
import argparse

lemma = nltk.wordnet.WordNetLemmatizer()

class CHAIR(object):

    def __init__(self, imids, coco_path):

        self.imid_to_objects = {imid: [] for imid in imids}

        self.coco_path = coco_path

        #read in synonyms
        synonyms = open('data/synonyms.txt').readlines()
        synonyms = [s.strip().split(', ') for s in synonyms]
        self.mscoco_objects = [] #mscoco objects and *all* synonyms
        self.inverse_synonym_dict = {}
        for synonym in synonyms:
            self.mscoco_objects.extend(synonym)
            for s in synonym:
                self.inverse_synonym_dict[s] = synonym[0]

        #Some hard coded rules for implementing CHAIR metrics on MSCOCO
        
        #common 'double words' in MSCOCO that should be treated as a single word
        coco_double_words = ['motor bike', 'motor cycle', 'air plane', 'traffic light', 'street light', 'traffic signal', 'stop light', 'fire hydrant', 'stop sign', 'parking meter', 'suit case', 'sports ball', 'baseball bat', 'baseball glove', 'tennis racket', 'wine glass', 'hot dog', 'cell phone', 'mobile phone', 'teddy bear', 'hair drier', 'potted plant', 'bow tie', 'laptop computer', 'stove top oven', 'hot dog', 'teddy bear', 'home plate']
        
        #Hard code some rules for special cases in MSCOCO
        #qualifiers like 'baby' or 'adult' animal will lead to a false fire for the MSCOCO object 'person'.  'baby bird' --> 'bird'.
        animal_words = ['bird', 'cat', 'dog', 'horse', 'sheep', 'cow', 'elephant', 'bear', 'zebra', 'giraffe', 'animal', 'cub']
        #qualifiers like 'passenger' vehicle will lead to a false fire for the MSCOCO object 'person'.  'passenger jet' --> 'jet'.
        vehicle_words = ['jet', 'train']
        
        #double_word_dict will map double words to the word they should be treated as in our analysis
        
        self.double_word_dict = {}
        for double_word in coco_double_words:
            self.double_word_dict[double_word] = double_word
        for animal_word in animal_words:
            self.double_word_dict['baby %s' %animal_word] = animal_word
            self.double_word_dict['adult %s' %animal_word] = animal_word
        for vehicle_word in vehicle_words:
            self.double_word_dict['passenger %s' %vehicle_word] = vehicle_word
        self.double_word_dict['bow tie'] = 'tie'
        self.double_word_dict['toilet seat'] = 'toilet'
        self.double_word_dict['wine glas'] = 'wine glass'

    def _load_generated_captions_into_evaluator(self, cap_file):

        '''
        Meant to save time so imid_to_objects does not always need to be recomputed.
        '''
        #Read in captions        
        self.caps, imids, self.metrics = load_generated_captions(cap_file)

        assert imids == set(self.imid_to_objects.keys())

    def caption_to_words(self, caption):
    
        '''
        Input: caption
        Output: MSCOCO words in the caption
        '''
    
        #standard preprocessing
        words = nltk.word_tokenize(caption.lower())
        words = [singularize(w) for w in words]
    
        #replace double words
        i = 0
        double_words = []
        while i < len(words):
           double_word = ' '.join(words[i:i+2])
           if double_word in self.double_word_dict: 
               double_words.append(self.double_word_dict[double_word])
               i += 2
           else:
               double_words.append(words[i])
               i += 1 
        words = double_words
    
        #toilet seat is not chair
        if ('toilet' in words) & ('seat' in words): words = [word for word in words if word != 'seat']
    
        #get synonyms for all words in the caption
        words = [word for word in words if word in set(self.mscoco_objects)]
        node_words = []
        for word in words:
            node_words.append(self.inverse_synonym_dict[word])
        #return all the MSCOCO objects in the caption
        return words, node_words

    def get_annotations_from_segments(self):
        '''
        Add objects taken from MSCOCO segmentation masks
        '''

        coco_segments = json.load(open(self.coco_path + '/instances_all2014.json'))
        segment_annotations = coco_segments['annotations']

        #make dict linking object name to ids
        id_to_name = {} #dict with id to synsets 
        for cat in coco_segments['categories']:
            id_to_name[cat['id']] = cat['name']

        for i, annotation in enumerate(segment_annotations):
            sys.stdout.write("\rGetting annotations for %d/%d segmentation masks" 
                              %(i, len(segment_annotations)))
            imid = annotation['image_id']
            if imid in self.imid_to_objects:
                node_word = self.inverse_synonym_dict[id_to_name[annotation['category_id']]]
                self.imid_to_objects[imid].append(node_word)
        print "\n"
        for imid in self.imid_to_objects:
            self.imid_to_objects[imid] = set(self.imid_to_objects[imid])

    def get_annotations_from_captions(self):
        '''
        Add objects taken from MSCOCO ground truth captions 
        '''

        coco_caps = json.load(open(self.coco_path + '/captions_all2014.json'))
        caption_annotations = coco_caps['annotations']

        for i, annotation in enumerate(caption_annotations):
            sys.stdout.write('\rGetting annotations for %d/%d ground truth captions' 
                              %(i, len(coco_caps['annotations'])))
            imid = annotation['image_id']
            if imid in self.imid_to_objects:
                words, node_words = self.caption_to_words(annotation['caption'])
                self.imid_to_objects[imid].update(node_words)
        print "\n"

        for imid in self.imid_to_objects:
            self.imid_to_objects[imid] = set(self.imid_to_objects[imid])

    def get_annotations(self):
        '''
        Get annotations from both segmentation and captions.  Need both annotation types for CHAIR metric.
        '''

        self.get_annotations_from_segments() 
        self.get_annotations_from_captions() 

    def compute_chair(self, cap_file):
    
        '''
        Given ground truth objects and generated captions, determine which sentences have hallucinated words.
        '''
    
        self._load_generated_captions_into_evaluator(cap_file)

        imid_to_objects = self.imid_to_objects
        caps = self.caps
 
        num_caps = 0.
        num_hallucinated_caps = 0.
        hallucinated_word_count = 0.
        coco_word_count = 0.

        output = {'sentences': []} 
    
        for i, cap_eval in enumerate(caps):
    
            cap = cap_eval['caption']
            imid = cap_eval['image_id']
    
            #get all words in the caption, as well as all synonyms
            words, node_words = self.caption_to_words(cap) 
    
            gt_objects = imid_to_objects[imid]
            cap_dict = {'image_id': cap_eval['image_id'], 
                        'caption': cap,
                        'hallucinated_words': [],
                        'gt_objects': list(gt_objects),
                        }
   
            cap_dict['metrics'] = {'Bleu_1': cap_eval['Bleu_1'],
                                   'Bleu_2': cap_eval['Bleu_2'],
                                   'Bleu_3': cap_eval['Bleu_3'],
                                   'Bleu_4': cap_eval['Bleu_4'],
                                   'METEOR': cap_eval['METEOR'],
                                   'CIDEr': cap_eval['CIDEr'],
                                   'SPICE': cap_eval['SPICE'],
                                   'ROUGE_L': cap_eval['ROUGE_L'],
                                   'CHAIRs': 0,
                                   'CHAIRi': 0}
 
            #count hallucinated words
            coco_word_count += len(node_words) 
            hallucinated = False
            for word, node_word in zip(words, node_words):
                if node_word not in gt_objects:
                    hallucinated_word_count += 1 
                    cap_dict['hallucinated_words'].append((word, node_word))
                    hallucinated = True      
    
            #count hallucinated caps
            num_caps += 1
            if hallucinated:
               num_hallucinated_caps += 1
    
            cap_dict['metrics']['chair_s'] = int(hallucinated)
            cap_dict['metrics']['chair_i'] = 0
            if len(words) > 0:
                cap_dict['metrics']['chair_i'] = len(cap_dict['hallucinated_words'])/float(len(words))
   
            output['sentences'].append(cap_dict)
 
        chair_s = (num_hallucinated_caps/num_caps)
        chair_i = (hallucinated_word_count/coco_word_count)
    
        output['overall_metrics'] = {'Bleu_1': self.metrics['Bleu_1'],
                                     'Bleu_2': self.metrics['Bleu_2'],
                                     'Bleu_3': self.metrics['Bleu_3'],
                                     'Bleu_4': self.metrics['Bleu_4'],
                                     'METEOR': self.metrics['METEOR'],
                                     'CIDEr': self.metrics['CIDEr'],
                                     'SPICE': self.metrics['SPICE'],
                                     'ROUGE_L': self.metrics['ROUGE_L'],
                                     'CHAIRs': chair_s,
                                     'CHAIRi': chair_i}
    
        return output 

def load_generated_captions(cap_file):
   #Read in captions        
   caps = json.load(open(cap_file))
   try:
       metrics = caps['overall']
       caps = caps['imgToEval'].values()
       imids = set([cap['image_id'] for cap in caps])
   except:
       raise Exception("Expect caption file to consist of a dectionary with sentences correspdonding to the key 'imgToEval'")

   return caps, imids, metrics

def save_hallucinated_words(cap_file, cap_dict): 
    tag = cap_file.split('/')[-1] 
    with open('output/hallucinated_words_%s' %tag, 'w') as f:
        json.dump(cap_dict, f)

def print_metrics(hallucination_cap_dict, quiet=False):
    sentence_metrics = hallucination_cap_dict['overall_metrics']
    metric_string = "%0.01f\t%0.01f\t%0.01f\t%0.01f\t%0.01f" %(
                                                  sentence_metrics['SPICE']*100,
                                                  sentence_metrics['METEOR']*100,
                                                  sentence_metrics['CIDEr']*100,
                                                  sentence_metrics['CHAIRs']*100,
                                                  sentence_metrics['CHAIRi']*100)

    if not quiet:
        print "SPICE\tMETEOR\tCIDEr\tCHAIRs\tCHAIRi"
        print metric_string

    else:
        return metric_string
 
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--cap_file", type=str, default='')
    parser.add_argument("--coco_path", type=str, default='coco')
    args = parser.parse_args()

    _, imids, _ = load_generated_captions(args.cap_file)

    evaluator = CHAIR(imids, args.coco_path) 
    evaluator.get_annotations()
    cap_dict = evaluator.compute_chair(args.cap_file) 
    
    print_metrics(cap_dict)
    save_hallucinated_words(args.cap_file, cap_dict)