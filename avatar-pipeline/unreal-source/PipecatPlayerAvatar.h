#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"

#include "PipecatPlayerAvatar.generated.h"

class ACharacter;
class USkeletalMesh;
class USkeletalMeshComponent;

// Reshapes the default avatar: swaps the player's body for Kalina, who is skinned onto the SAME mannequin skeleton
// (SK_Mannequin), so the template's animation Blueprint, animations and camera keep working untouched.
// Added to the player pawn by UPipecatDemoSubsystem when play begins; -PipecatNoAvatar keeps the stock mannequin.
UCLASS(ClassGroup = (Pipecat))
class UPipecatPlayerAvatar : public UActorComponent
{
	GENERATED_BODY()

public:
	UPipecatPlayerAvatar();

	UPROPERTY(EditAnywhere, Category = "Avatar")
	TSoftObjectPtr<USkeletalMesh> Mesh;

	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

protected:
	virtual void BeginPlay() override;

private:
	UPROPERTY()
	TObjectPtr<ACharacter> Character;

	UPROPERTY()
	TObjectPtr<USkeletalMeshComponent> Body;

	// Testing aids for the headless camera (see PipecatCaptureSubsystem):
	//   -PipecatAvatarPreview          close-up camera that slowly orbits her
	//   -PipecatAvatarPose=Ref|Idle|Walk|Run
	//        Ref  = the skeleton's reference pose, no animation (checks the rig and skinning)
	//        Walk/Run = the character is walked forward so the template's own locomotion animations play
	bool bPreview = false;
	float PreviewYaw = 0.0f;
	FString ForcedPose;
};
