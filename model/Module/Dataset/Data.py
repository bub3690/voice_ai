import pickle
import os
import pandas as pd

def make_data(dataset):
    if dataset == 'phrase':
        phras_file_path = "../../voice_data/all_data_ver2/phrase_dict_ver2_all.pickle"
        phras_file_path_abs = os.path.abspath(phras_file_path)
    elif dataset == 'phrase_egg_fusion':
        #egg 추가하기.
        print('egg')
        fusion_file_list = [os.path.abspath("../../voice_data/all_data_ver2/phrase_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/phrase_dict_ver2_EGG_all.pickle"),
                            ]                
    elif dataset == 'a_h':
        phras_file_path = "../../voice_data/all_data_ver2/a_high_dict_ver2_all.pickle"
        phras_file_path_abs = os.path.abspath(phras_file_path)
    elif dataset == 'a_l':
        phras_file_path = "../../voice_data/all_data_ver2/a_low_dict_ver2_all.pickle"
        phras_file_path_abs = os.path.abspath(phras_file_path)
    elif dataset == 'a_n':
        phras_file_path = "../../voice_data/all_data_ver2/a_normal_dict_ver2_all.pickle"
        phras_file_path_abs = os.path.abspath(phras_file_path)
    elif dataset == 'a_fusion':
        fusion_file_list = [os.path.abspath("../../voice_data/all_data_ver2/a_high_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/a_low_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/a_normal_dict_ver2_all.pickle")
                            ]
        fusion_name_list = ["a_h","a_l","a_n"]
    elif dataset == 'i_h':
        phras_file_path = "../../voice_data/all_data_ver2/i_high_dict_ver2_all.pickle"
        phras_file_path_abs = os.path.abspath(phras_file_path)
    elif dataset == 'i_l':
        phras_file_path = "../../voice_data/all_data_ver2/i_low_dict_ver2_all.pickle"
        phras_file_path_abs = os.path.abspath(phras_file_path)
    elif dataset == 'i_n':
        phras_file_path = "../../voice_data/all_data_ver2/i_normal_dict_ver2_all.pickle"
        phras_file_path_abs = os.path.abspath(phras_file_path)
    elif dataset == 'i_fusion':
        fusion_file_list = [os.path.abspath("../../voice_data/all_data_ver2/i_high_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/i_low_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/i_normal_dict_ver2_all.pickle")
                            ]
        fusion_name_list = ["i_h","i_l","i_n"]
    elif dataset == 'u_h':
        phras_file_path = "../../voice_data/all_data_ver2/u_high_dict_ver2_all.pickle"
        phras_file_path_abs = os.path.abspath(phras_file_path)
    elif dataset == 'u_l':
        phras_file_path = "../../voice_data/all_data_ver2/u_low_dict_ver2_all.pickle"
        phras_file_path_abs = os.path.abspath(phras_file_path)
    elif dataset == 'u_n':
        phras_file_path = "../../voice_data/all_data_ver2/u_normal_dict_ver2_all.pickle"
        phras_file_path_abs = os.path.abspath(phras_file_path)
    elif dataset == 'u_fusion':
        fusion_file_list = [os.path.abspath("../../voice_data/all_data_ver2/u_high_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/u_low_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/u_normal_dict_ver2_all.pickle")
                            ]
        fusion_name_list = ["u_h","u_l","u_n"]
    elif dataset == 'aiu_n_fusion':
        fusion_file_list = [os.path.abspath("../../voice_data/all_data_ver2/a_normal_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/i_normal_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/u_normal_dict_ver2_all.pickle")
                            ]
    elif dataset == 'aiu_h_fusion':
        fusion_file_list = [os.path.abspath("../../voice_data/all_data_ver2/a_high_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/i_high_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/u_high_dict_ver2_all.pickle")
                            ]
    elif dataset == 'aiu_l_fusion':
        fusion_file_list = [os.path.abspath("../../voice_data/all_data_ver2/a_low_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/i_low_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/u_low_dict_ver2_all.pickle")
                            ]
    elif dataset == 'phrase_a_fusion':
        fusion_file_list = [os.path.abspath("../../voice_data/all_data_ver2/phrase_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/a_high_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/a_low_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/a_normal_dict_ver2_all.pickle")
                            ]
    elif dataset == 'phrase_i_fusion':
        fusion_file_list = [os.path.abspath("../../voice_data/all_data_ver2/phrase_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/i_high_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/i_low_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/i_normal_dict_ver2_all.pickle")
                            ]
    elif dataset == 'phrase_u_fusion':
        fusion_file_list = [os.path.abspath("../../voice_data/all_data_ver2/phrase_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/u_high_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/u_low_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/u_normal_dict_ver2_all.pickle")
                            ]
    elif dataset == 'vowel_fusion':
        fusion_file_list = [
                            os.path.abspath("../../voice_data/all_data_ver2/a_high_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/a_low_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/a_normal_dict_ver2_all.pickle"),

                            os.path.abspath("../../voice_data/all_data_ver2/i_high_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/i_low_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/i_normal_dict_ver2_all.pickle"),

                            os.path.abspath("../../voice_data/all_data_ver2/u_high_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/u_low_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/u_normal_dict_ver2_all.pickle"),
                            ]        
                            
    elif dataset == 'all_fusion':
        fusion_file_list = [
                            os.path.abspath("../../voice_data/all_data_ver2/phrase_dict_ver2_all.pickle"),

                            os.path.abspath("../../voice_data/all_data_ver2/a_high_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/a_low_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/a_normal_dict_ver2_all.pickle"),

                            os.path.abspath("../../voice_data/all_data_ver2/i_high_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/i_low_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/i_normal_dict_ver2_all.pickle"),

                            os.path.abspath("../../voice_data/all_data_ver2/u_high_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/u_low_dict_ver2_all.pickle"),
                            os.path.abspath("../../voice_data/all_data_ver2/u_normal_dict_ver2_all.pickle"),

                            ]
        fusion_name_list = ["phrase","a_h","a_l","a_n","i_h","i_l","i_n","u_h","u_l","u_n"]
        
    else:
        phras_file_path = "../../voice_data/all_data_ver2/phrase_dict_ver2_all.pickle"
        phras_file_path_abs = os.path.abspath(phras_file_path)


    if len(dataset.split('_'))>1 and 'fusion' in dataset.split('_')[-1]:
        #fusion data 구성
        print("데이터 로드 " + dataset)
        data_instance = FusionData(fusion_file_list) #class에 데이터를 담아준다.
    else:
        print("데이터 로드 "+dataset)
        data_instance = PhraseData(phras_file_path_abs) #class에 데이터를 담아준다.
    return data_instance


def get_opensmile(opensmile_path):
    opensmile_path_abs = os.path.abspath(opensmile_path)
    print("데이터 로드 opensmile")
    data_instance = OpensmileData(opensmile_path_abs) #class에 데이터를 담아준다.
    return data_instance

def get_glottal(glottal_path):
    glottal_path_abs = os.path.abspath(glottal_path)
    print("데이터 로드 glottal")
    data_instance = GlottalData(glottal_path_abs) #class에 데이터를 담아준다.
    return data_instance


class PhraseData():
    
    phrase_dict = dict()

    dict_list = [] # fusion을 위한 dict 리스트

    def __init__(self,phrase_path):
        #load
        
        with open(phrase_path,"rb") as fr:
            PhraseData.phrase_dict = pickle.load(fr)
        return

class FusionData():

    dict_list = [] # fusion을 위한 dict 리스트

    def __init__(self,path_list):
        #load
        
        for wav_path in path_list:
            with open(wav_path,"rb") as fr:
                FusionData.dict_list.append(pickle.load(fr))
        return


class OpensmileData():
    
    opensmile_dict = dict()
    scaler_list = []

    def __init__(self,opensmile_path):
        #load
        with open(opensmile_path,"rb") as fr:
            OpensmileData.opensmile_dict = pickle.load(fr)
        return
    
class GlottalData():

    glottal_table = None
    scaler_list = []

    def __init__(self,glottal_path):
        #load

        GlottalData.glottal_table = pd.read_excel(glottal_path)
        return